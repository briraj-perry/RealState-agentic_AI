import json
import re
from datetime import datetime

from pydantic import BaseModel, ValidationError

from estate_ai.db import (
    Audit,
    Customer,
    Message,
    Property,
    PropertyListing,
    PropertyMetadata,
    PropertyPhoto,
    Proposal,
    TestSession,
    now,
)
from estate_ai.document_query import load_only, object_session, select
from estate_ai.photos import photo_data
from estate_ai.schemas import (
    HandoffArgs,
    PreferenceArgs,
    PriceArgs,
    PropertyArgs,
    RelatedArgs,
    SearchArgs,
    VisitArgs,
    validate_visit_date,
)


def property_data(row: Property, include_internal: bool = False, related: dict | None = None) -> dict:
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
        if session and related is None
        else []
    )
    if related is not None:
        photos = related["photos"].get(row.id, [])
    metadata = (
        related["metadata"].get(row.id)
        if related is not None
        else session.get(PropertyMetadata, row.id)
        if session
        else None
    )
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
    if include_internal:
        mappings = (
            related["listings"].get(row.id, [])
            if related is not None
            else (
                list(session.scalars(select(PropertyListing).where(PropertyListing.property_id == row.id)))
                if session
                else []
            )
        )
        result["housing_listing_ids"] = [mapping.id for mapping in mappings]
    return result


def related_note(row: Property, anchor: Property) -> str:
    location = (
        "Same locality" if row.locality.casefold() == anchor.locality.casefold() else "Different locality"
    )
    difference = row.asking_price - anchor.asking_price
    price = (
        "Same asking price as selected property"
        if difference == 0
        else f"INR {abs(difference):,} {'higher' if difference > 0 else 'lower'} asking price than selected property"
    )
    return f"Same city · {row.bedrooms} BHK · {location} · {price}"


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
    "find_related_properties": (
        RelatedArgs,
        (
            "Find related available homes for a property ID, or the buyer's selected property if omitted. "
            "Same city and BHK, within 20% of its asking price and within the buyer's stated budget if known. "
            "Exclude already seen listings by default. Never silently widen the criteria."
        ),
    ),
    "save_preferences": (PreferenceArgs, "Record nonfinancial requirements explicitly stated by this buyer."),
    "propose_price_confirmation": (
        PriceArgs,
        "Prepare buyer confirmation of a budget or property offer. Never approve a sale.",
    ),
    "request_site_visit": (
        VisitArgs,
        (
            "Prepare a site-visit request for tomorrow in Asia/Kolkata. Use the buyer's chosen time. "
            "The buyer must confirm the request before it is sent for dealer approval."
        ),
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

    def interested_property_id(self) -> str:
        test = self.session.get(TestSession, self.phone)
        if test:
            return test.property_id
        customer = self.session.get(Customer, self.phone)
        return customer.interest_property_id if customer else ""

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
        return query.order_by(Property.demo, Property.asking_price, Property.id)

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

    def related_candidates(self, args: RelatedArgs):
        property_id = args.property_id or self.interested_property_id()
        if not property_id:
            raise ValueError("Choose a property first so I can find related homes")
        anchor = self.property(property_id)
        ceiling, floor = anchor.asking_price * 120 // 100, anchor.asking_price * 80 // 100
        budget = self.session.scalar(
            select(Proposal)
            .where(
                Proposal.phone == self.phone,
                Proposal.kind == "budget",
                Proposal.status.in_(["pending_confirmation", "buyer_confirmed"]),
            )
            .order_by(Proposal.created.desc())
            .limit(1)
        )
        stated_budget = json.loads(budget.payload).get("amount_inr") if budget else None
        if stated_budget:
            ceiling = min(ceiling, stated_budget)
        query = select(Property).where(
            Property.available.is_(True),
            Property.demo == anchor.demo,
            Property.city.ilike(anchor.city),
            Property.bedrooms == anchor.bedrooms,
            Property.asking_price <= ceiling,
        )
        seen = {anchor.id}
        if args.exclude_seen:
            for detail in self.session.scalars(
                select(Audit.detail).where(
                    Audit.phone == self.phone, Audit.action == "property_search_results"
                )
            ):
                seen.update(json.loads(detail).get("property_ids", []))
        rows = [
            row for row in self.session.scalars(query) if row.id not in seen and row.asking_price >= floor
        ]
        rows.sort(
            key=lambda row: (
                row.locality.casefold() != anchor.locality.casefold(),
                abs(row.asking_price - anchor.asking_price),
                row.id,
            )
        )
        return (
            anchor,
            rows,
            {
                "city": anchor.city,
                "bedrooms": anchor.bedrooms,
                "min_price_inr": floor,
                "max_price_inr": ceiling,
                "stated_budget_inr": stated_budget,
            },
        )

    def find_related_properties(self, args: RelatedArgs):
        anchor, candidates, basis = self.related_candidates(args)
        properties = [
            {**property_data(row), "match_note": related_note(row, anchor)}
            for row in candidates[: args.limit]
        ]
        self.session.add(
            Audit(
                phone=self.phone,
                action="property_search_results",
                detail=json.dumps(
                    {
                        "kind": "related",
                        "source_property_id": anchor.id,
                        "property_ids": [p["id"] for p in properties],
                        "source_message_id": self.message_id,
                        "basis": basis,
                        "filters": {
                            "city": anchor.city,
                            "bedrooms": anchor.bedrooms,
                            "max_price": basis["max_price_inr"],
                        },
                    }
                ),
            )
        )
        return {
            "properties": properties,
            "source_property_id": anchor.id,
            "basis": basis,
            "has_more": len(candidates) > args.limit,
            "note": "Related to the selected listing, not proof of the buyer's preferences. "
            "No city, size or price range was widened. Fictional listings remain fictional.",
        }

    def related_properties(self):
        result = self.execute("find_related_properties", {})
        if "error" in result:
            return result["error"]
        basis = result["basis"]
        if basis["max_price_inr"] < basis["min_price_inr"]:
            return (
                f"Your stated budget of INR {basis['stated_budget_inr']:,} is below the similar-price "
                f"range for {result['source_property_id']} (starting at INR {basis['min_price_inr']:,}). "
                "I haven't shown above-budget homes. Would you like to search a lower price range instead?"
            )
        criteria = (
            f"{basis['bedrooms']} BHK in {basis['city']}, asking price "
            f"INR {basis['min_price_inr']:,}–{basis['max_price_inr']:,}"
        )
        if not result["properties"]:
            return (
                f"There are no more unseen related homes for {result['source_property_id']} "
                f"with these criteria: {criteria}. I haven't widened the search. "
                "Would you like to change the price range, location or bedrooms?"
            )
        lines = [f"Here are related homes for {result['source_property_id']}: {criteria}."]
        for p in result["properties"]:
            label = "Fictional demo · " if p["demo"] else ""
            lines.append(
                f"{label}{p['id']} — {p['title']}, {p['locality']}. "
                f"Asking price INR {p['asking_price_inr']:,}. {p['match_note']}."
            )
        lines.append("Asking prices are not agreed sale prices. Which home would you like to explore?")
        return "\n\n".join(lines)

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
        args.limit = 10
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
        result = self.execute("search_properties", {})
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
            "confirmation_instruction": "State the exact details and ask the buyer whether to confirm.",
            "notice": "Offers need dealer approval. Visits are requests, not booked appointments.",
        }

    def budget_shortlist(self, proposal):
        data = json.loads(proposal.payload)
        budget = data["amount_inr"]
        selected = self.interested_property_id()
        mentioned = data.get("property_id")
        if (
            mentioned
            and mentioned.casefold() in self.session.get(Message, self.message_id).content.casefold()
        ):
            selected = mentioned
        anchor = self.property(selected) if selected else None
        filters = {}
        latest = self.session.scalar(
            select(Audit.detail)
            .where(Audit.phone == self.phone, Audit.action == "property_search_results")
            .order_by(Audit.created.desc())
            .limit(1)
        )
        if latest:
            filters = json.loads(latest).get("filters", {})
        criteria = {key: filters.get(key) for key in ("city", "locality", "bedrooms")}
        if anchor:
            criteria["city"] = criteria["city"] or anchor.city
        matches = self.search_properties(SearchArgs(max_price=budget, **criteria))["properties"]
        lines = [
            f"{p['title']} ({p['id']}) in {p['locality']}, {p['city']} — ₹{p['asking_price_inr']:,}."
            for p in matches
        ]
        if not lines:
            lines.append("I found no available properties within that budget and your current criteria.")
        if not anchor and len(matches) == 1:
            anchor = self.property(matches[0]["id"])
        if anchor and anchor.available:
            data["property_id"] = anchor.id
            question = f" and your interest in {anchor.title} ({anchor.id})"
        else:
            data["property_id"] = None
            question = ""
        proposal.payload = json.dumps(data, sort_keys=True)
        lines.append(f"Should I confirm your budget of ₹{budget:,}{question}?")
        return "\n\n".join(lines)

    def confirmation_question(self, row):
        data = json.loads(row.payload)
        if row.kind == "visit":
            when = datetime.fromisoformat(data["start_time"]).strftime("%d %b %Y at %H:%M (UTC%z)")
            return f"Should I confirm your site-visit request for {data['property_id']} on {when}?"
        return f"Should I confirm your offer of ₹{data['amount_inr']:,} for {data['property_id']}?"

    def proposal_response(self, text):
        clean = text.strip().casefold().rstrip(".!?")
        if clean in {
            "yes",
            "yes please",
            "yes, please",
            "yes confirm",
            "yes, confirm",
            "yes please confirm",
            "confirm it",
            "confirm",
            "sure",
            "ok",
            "okay",
            "haan",
            "हाँ",
        }:
            source = self.session.get(Message, self.message_id)
            previous = self.session.scalar(
                select(Message)
                .where(
                    Message.phone == self.phone,
                    Message.created <= source.created,
                    Message.id.not_in([source.id]),
                )
                .order_by(Message.created.desc())
                .limit(1)
            )
            if previous and previous.role == "assistant" and previous.id.startswith("reply:"):
                rows = self.session.scalars(
                    select(Proposal).where(
                        Proposal.phone == self.phone,
                        Proposal.source_message_id == previous.id[6:],
                    )
                )
                for row in rows:
                    if row.kind == "budget":
                        amount = json.loads(row.payload)["amount_inr"]
                        question = previous.content.split("\n")[-1]
                        prefix = f"Should I confirm your budget of ₹{amount:,}"
                        asked = question == prefix + "?" or question.startswith(
                            prefix + " and your interest in "
                        )
                    else:
                        asked = previous.content == self.confirmation_question(row)
                    if asked:
                        return confirm_proposal(
                            self.session, self.phone, "CONFIRM " + row.id, self.message_id
                        )
        match = re.fullmatch(
            r"(?:my |our )?budget(?: is| of)?[ :₹]*(?:rs\.? *|inr *)?([0-9][0-9,]*(?:\.[0-9]+)?) *(lakhs?|lacs?|crores?|cr|l|k)?(?: rupees)?",
            clean,
        )
        if match:
            unit = match[2] or ""
            multiplier = (
                100000
                if unit.startswith("l")
                else 10000000
                if unit.startswith("c")
                else 1000
                if unit == "k"
                else 1
            )
            value = float(match[1].replace(",", "")) * multiplier
            if 1 <= value <= 2_000_000_000:
                result = self.propose_price_confirmation(PriceArgs(kind="budget", amount_inr=round(value)))
                return self.budget_shortlist(self.session.get(Proposal, result["proposal_id"]))
        return None

    def propose_price_confirmation(self, args: PriceArgs):
        source = self.session.get(Message, self.message_id)
        if source and source.content.strip().casefold().rstrip(".!?") in {
            "hi",
            "hello",
            "hey",
            "namaste",
            "yes",
            "no",
        }:
            raise ValueError("The buyer did not state an amount in this message")
        if args.kind == "offer" and not args.property_id:
            raise ValueError("An offer requires a property reference")
        if args.property_id:
            self.property(args.property_id)
        return self.proposal(args.kind, args.model_dump())

    def request_site_visit(self, args: VisitArgs):
        row = self.property(args.property_id)
        if not row.available:
            raise ValueError("Property is unavailable")
        validate_visit_date(args.start_time)
        return self.proposal("visit", args.model_dump(mode="json"))

    def request_human_handoff(self, args: HandoffArgs):
        customer = self.session.get(Customer, self.phone)
        customer.paused = True
        test = self.session.get(TestSession, self.phone)
        messages = list(
            self.session.scalars(
                select(Message)
                .where(Message.phone == self.phone)
                .order_by(Message.created.desc(), Message.id.desc())
                .limit(8)
            )
        )
        preferences = list(
            self.session.scalars(
                select(Audit.detail)
                .where(Audit.phone == self.phone, Audit.action == "preferences")
                .order_by(Audit.created.desc())
                .limit(5)
            )
        )
        proposals = list(
            self.session.scalars(
                select(Proposal)
                .where(Proposal.phone == self.phone)
                .order_by(Proposal.created.desc())
                .limit(5)
            )
        )
        summary = {
            "reason": args.reason,
            "buyer_name": customer.name,
            "property_id": test.property_id if test else customer.interest_property_id,
            "listing_id": test.listing_id if test else "",
            "preferences_with_evidence": [json.loads(p) for p in preferences],
            "proposals": [
                {"kind": p.kind, "details": json.loads(p.payload), "status": p.status} for p in proposals
            ],
            "recent_messages": [{"role": m.role, "text": m.content[:1000]} for m in reversed(messages)],
            "delivery": "Saved for dealer review in Estate AI; no external notification sent",
        }
        self.session.add(
            Audit(phone=self.phone, action="dealer_alert", detail=json.dumps(summary, ensure_ascii=False))
        )
        return {"status": "human_followup_required", "bot_paused": True}


def confirm_proposal(session, phone: str, text: str, source_id: str) -> str:
    token = text.strip().split(maxsplit=1)
    if len(token) != 2 or token[0].casefold() != "confirm":
        return "Please tell me which details you would like to confirm."
    row = session.get(Proposal, token[1].strip())
    if not row or row.phone != phone:
        return "I couldn't find that confirmation request. Please share the details again."
    if row.created < now() - 86400:
        return "That confirmation request expired. Please send the details again."
    if row.status != "pending_confirmation":
        return "Those details have already been confirmed."
    if row.kind == "visit":
        try:
            visit = VisitArgs.model_validate_json(row.payload)
            validate_visit_date(visit.start_time)
        except ValidationError:
            return "Please send a new visit time for tomorrow in India time."
        except ValueError as exc:
            return str(exc)
        property_row = session.get(Property, visit.property_id)
        if not property_row or not property_row.available:
            return "That property is no longer available. I'll need to find an alternative."
    row.status = "requested" if row.kind == "visit" else "buyer_confirmed"
    if row.kind == "visit" and row.calendar_state != "saved":
        row.calendar_state = "pending"
        row.calendar_retry_at = now()
    row.confirmation_message_id = source_id
    session.add(Audit(phone=phone, action="dealer_alert", detail=f"Confirmed {row.kind}: {row.id}"))
    if row.kind == "visit":
        return "Your site-visit request is recorded. The dealer still needs to confirm availability; it isn't booked yet."
    if row.kind == "offer":
        return "Your offer is recorded and awaits the dealer's approval. This is not an agreed sale price."
    property_id = json.loads(row.payload).get("property_id")
    if property_id:
        return f"Thanks, your budget and interest in {property_id} are confirmed. Would you like more details about this property?"
    return "Thanks, your budget is confirmed and saved. Which property interests you?"
