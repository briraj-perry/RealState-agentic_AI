import json
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ValidationError

from estate_ai.db import Audit, Customer, Property, PropertyMetadata, PropertyPhoto, Proposal, now
from estate_ai.document_query import load_only, object_session, select
from estate_ai.photos import photo_data
from estate_ai.schemas import (
    HandoffArgs,
    PreferenceArgs,
    PriceArgs,
    PropertyArgs,
    SearchArgs,
    VisitArgs,
)


def property_data(row: Property, include_internal: bool = False) -> dict:
    session = object_session(row)
    photos = (
        list(
            session.scalars(
                select(PropertyPhoto)
                .options(load_only(PropertyPhoto.id, PropertyPhoto.created))
                .where(PropertyPhoto.property_id == row.id)
                .order_by(PropertyPhoto.created)
            )
        )
        if session
        else []
    )
    metadata = session.get(PropertyMetadata, row.id) if session else None
    source = json.loads(metadata.payload) if metadata else {}
    result = {
        "id": row.id,
        "title": row.title,
        "city": row.city,
        "locality": row.locality,
        "bedrooms": row.bedrooms,
        "asking_price_inr": row.asking_price,
        "available": row.available,
        "verified_at": row.verified_at,
        "description": row.description,
        "demo": row.demo,
        "photos": [photo_data(photo) for photo in photos],
        "details": source.get("details", {}),
        "price_note": "Asking price only; final price and additional charges require dealer confirmation.",
    }
    if include_internal and source:
        result["import_source"] = {key: value for key, value in source.items() if key != "details"}
    return result


TOOL_SPECS: dict[str, tuple[type[BaseModel], str]] = {
    "search_properties": (
        SearchArgs,
        (
            "Search available inventory by city, locality, bedrooms and INR budget. "
            "Return up to limit matches (1–10). Use exclude_seen=true when the buyer asks for more or different "
            "options; this excludes listings retrieved earlier for THIS buyer. Never silently relax filters."
        ),
    ),
    "get_property_details": (PropertyArgs, "Read inventory facts and price verification time."),
    "save_preferences": (PreferenceArgs, "Record nonfinancial requirements explicitly stated by this buyer."),
    "propose_price_confirmation": (
        PriceArgs,
        "Prepare buyer confirmation of a budget or property offer. Never approve a sale.",
    ),
    "request_site_visit": (
        VisitArgs,
        "Prepare a site-visit REQUEST for buyer confirmation. Does NOT book a calendar slot.",
    ),
    "request_human_handoff": (HandoffArgs, "Pause the bot and alert the dealer when a human is needed."),
}


def tool_definitions() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": schema.model_json_schema()},
        }
        for name, (schema, description) in TOOL_SPECS.items()
    ]


class ToolService:
    """Identity and source evidence are bound by the server, never supplied by the model."""

    def __init__(self, session, phone: str, message_id: str, allow_demo: bool = False):
        self.session = session
        self.phone = phone
        self.message_id = message_id
        self.allow_demo = allow_demo

    def property(self, property_id: str) -> Property:
        row = self.session.get(Property, property_id)
        if not row or (row.demo and not self.allow_demo):
            raise ValueError("Property not found")
        return row

    def execute(self, name: str, arguments: dict) -> dict:
        if name not in TOOL_SPECS:
            return {"error": "Unknown tool"}
        customer = self.session.get(Customer, self.phone)
        if not customer or customer.opted_out or customer.paused:
            return {"error": "Automation is paused or contact opted out"}
        try:
            args = TOOL_SPECS[name][0].model_validate(arguments)
            result = getattr(self, name)(args)
            self.session.add(
                Audit(
                    phone=self.phone, action=name, detail=json.dumps({"source_message_id": self.message_id})
                )
            )
            self.session.flush()
            return result
        except ValidationError:
            return {"error": "Tool arguments are invalid; check the schema and ask the buyer if needed"}
        except ValueError as exc:
            return {"error": str(exc)}

    def search_query(self, args: SearchArgs):
        query = select(Property).where(Property.available.is_(True))
        if not self.allow_demo:
            query = query.where(Property.demo.is_(False))
        if args.city:
            query = query.where(Property.city.ilike(args.city))
        if args.locality:
            query = query.where(Property.locality.icontains(args.locality, autoescape=True))
        if args.max_price:
            query = query.where(Property.asking_price <= args.max_price)
        if args.bedrooms is not None:
            query = query.where(Property.bedrooms == args.bedrooms)
        if args.exclude_seen:
            seen_ids = set()
            for detail in self.session.scalars(
                select(Audit.detail)
                .where(Audit.phone == self.phone, Audit.action == "property_search_results")
                .order_by(Audit.created.desc())
                .limit(100)
            ):
                seen_ids.update(json.loads(detail).get("property_ids", []))
            if seen_ids:
                query = query.where(Property.id.not_in(seen_ids))
        return query.order_by(Property.asking_price, Property.id)

    def search_properties(self, args: SearchArgs):
        properties = [
            property_data(p) for p in self.session.scalars(self.search_query(args).limit(args.limit))
        ]
        self.session.add(
            Audit(
                phone=self.phone,
                action="property_search_results",
                detail=json.dumps(
                    {
                        "property_ids": [p["id"] for p in properties],
                        "source_message_id": self.message_id,
                        "filters": args.model_dump(),
                    }
                ),
            )
        )
        self.session.flush()
        return {"properties": properties}

    def get_property_details(self, args: PropertyArgs):
        return property_data(self.property(args.property_id))

    def more_properties(self):
        detail = self.session.scalar(
            select(Audit.detail)
            .where(Audit.phone == self.phone, Audit.action == "property_search_results")
            .order_by(Audit.created.desc())
            .limit(1)
        )
        if not detail:
            return "Tell me your preferred location, budget or bedrooms first, so I can find suitable properties."
        args = SearchArgs.model_validate(json.loads(detail).get("filters", {}))
        args.exclude_seen = True
        args.limit = 5
        result = self.execute("search_properties", args.model_dump())
        if "error" in result:
            return "I couldn't retrieve more properties: " + result["error"]
        properties = result["properties"]
        if not properties:
            return (
                "There are no more available properties matching this search that we haven't already "
                "looked at. Would you like to change the location, budget or number of bedrooms?"
            )
        lines = [f"Here are {len(properties)} more matching options from the inventory:"]
        for p in properties:
            label = "Fictional demo · " if p["demo"] else ""
            lines.append(
                f"{label}{p['id']} — {p['bedrooms']} BHK in {p['locality']}, {p['city']}. "
                f"Asking price: INR {p['asking_price_inr']:,}."
            )
        lines.append(
            "These are asking prices, not final agreed prices. Which option would you like to explore?"
        )
        return "\n\n".join(lines)

    def browse_properties(self):
        result = self.execute("search_properties", {"limit": 3})
        if "error" in result:
            return "I couldn't browse the inventory: " + result["error"]
        if not result["properties"]:
            return "There are no available properties in the accessible inventory yet. Please add a listing in Properties."
        return (
            "Here are some available properties from the full inventory, across all locations and "
            "budgets. They are shown as cards below. Demo listings are fictional. "
            "What location, budget and number of bedrooms would suit you?"
        )

    def save_preferences(self, args: PreferenceArgs):
        data = args.model_dump(exclude_none=True)
        self.session.add(
            Audit(
                phone=self.phone,
                action="preferences",
                detail=json.dumps({"values": data, "source_message_id": self.message_id}),
            )
        )
        return {"saved": data}

    def proposal(self, kind: str, data: dict):
        encoded = json.dumps(data, sort_keys=True)
        previous = self.session.scalar(
            select(Proposal).where(
                Proposal.phone == self.phone,
                Proposal.kind == kind,
                Proposal.source_message_id == self.message_id,
                Proposal.payload == encoded,
            )
        )
        if previous:
            row = previous
        else:
            row = Proposal(phone=self.phone, kind=kind, payload=encoded, source_message_id=self.message_id)
            self.session.add(row)
            self.session.flush()
        return {
            "proposal_id": row.id,
            "details": data,
            "status": row.status,
            "confirmation_instruction": f"Buyer must reply CONFIRM {row.id} to confirm these exact details.",
            "notice": "Offers need dealer approval. Visits are requests, not booked appointments.",
        }

    def propose_price_confirmation(self, args: PriceArgs):
        if args.kind == "offer" and not args.property_id:
            raise ValueError("An offer requires a property reference")
        if args.property_id:
            self.property(args.property_id)
        return self.proposal(args.kind, args.model_dump())

    def request_site_visit(self, args: VisitArgs):
        row = self.property(args.property_id)
        if not row.available:
            raise ValueError("Property is unavailable")
        current = datetime.now(UTC)
        if not current < args.start_time <= current + timedelta(days=90):
            raise ValueError("Visit must be in the future and within 90 days")
        return self.proposal("visit", args.model_dump(mode="json"))

    def request_human_handoff(self, args: HandoffArgs):
        self.session.get(Customer, self.phone).paused = True
        self.session.add(Audit(phone=self.phone, action="dealer_alert", detail=args.reason))
        return {"status": "human_followup_required", "bot_paused": True}


def confirm_proposal(session, phone: str, text: str, source_id: str) -> str:
    token = text.strip().split(maxsplit=1)
    if len(token) != 2 or token[0].casefold() != "confirm":
        return "Please reply with the full confirmation code shown with the details."
    row = session.get(Proposal, token[1].strip())
    if not row or row.phone != phone:
        return "I couldn't find that confirmation request. Please check the code."
    if row.created < now() - 86400:
        return "That confirmation request expired. Please send the details again."
    if row.status != "pending_confirmation":
        return "Those details have already been confirmed."
    if row.kind == "visit":
        data = json.loads(row.payload)
        property_row = session.get(Property, data["property_id"])
        if not property_row or not property_row.available:
            return "That property is no longer available. I'll need to find an alternative."
        if datetime.fromisoformat(data["start_time"]).timestamp() <= now():
            return "That visit time has passed. Please choose a new time."
    row.status = "requested" if row.kind == "visit" else "buyer_confirmed"
    row.confirmation_message_id = source_id
    session.add(Audit(phone=phone, action="dealer_alert", detail=f"Confirmed {row.kind}: {row.id}"))
    if row.kind == "visit":
        return "Your site-visit request is recorded. The dealer still needs to confirm availability; it isn't booked yet."
    if row.kind == "offer":
        return "Your offer is recorded and awaits the dealer's approval. This is not an agreed sale price."
    return "Thanks, your budget is confirmed and saved."
