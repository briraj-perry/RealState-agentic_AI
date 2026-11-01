"""Local dashboard UI and authenticated read models for the existing agent services."""

import json
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from sqlalchemy import func, select

from estate_ai.db import Audit, Customer, Job, Message, Property, Proposal, TestSession
from estate_ai.schemas import SearchArgs, StrictModel
from estate_ai.tools import ToolService, property_data
from estate_ai.workflows import enqueue

WEB = Path(__file__).parent / "web"


class SessionInput(StrictModel):
    name: str = Field(default="New test conversation", min_length=1, max_length=120)


def decode(value: str):
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return {}


def proposal_data(row):
    return {
        "id": row.id,
        "phone": row.phone,
        "kind": row.kind,
        "details": decode(row.payload),
        "status": row.status,
        "created": row.created,
        "source_message_id": row.source_message_id,
        "confirmation_message_id": row.confirmation_message_id,
    }


def register_dashboard(app, settings, admin):
    app.mount("/assets", StaticFiles(directory=WEB), name="dashboard-assets")

    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    def dashboard_page():
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})

    router = APIRouter(prefix="/api", dependencies=[Depends(admin)])

    def customers(session):
        rows = list(session.scalars(select(Customer).order_by(Customer.last_inbound.desc()).limit(200)))
        test_phones = set(session.scalars(select(TestSession.phone)))
        output = []
        for row in rows:
            recent = session.scalar(
                select(Message).where(Message.phone == row.phone).order_by(Message.created.desc()).limit(1)
            )
            preferences = {}
            evidence = []
            for audit in session.scalars(
                select(Audit)
                .where(Audit.phone == row.phone, Audit.action == "preferences")
                .order_by(Audit.created)
            ):
                data = decode(audit.detail)
                preferences.update(data.get("values", {}))
                evidence.append(data.get("source_message_id"))
            proposals = list(
                session.scalars(
                    select(Proposal).where(Proposal.phone == row.phone).order_by(Proposal.created.desc())
                )
            )
            budget = next(
                (p for p in proposals if p.kind == "budget" and p.status == "buyer_confirmed"), None
            )
            output.append(
                {
                    "phone": row.phone,
                    "name": row.name or "Buyer " + row.phone[-4:],
                    "paused": row.paused,
                    "opted_out": row.opted_out,
                    "test": row.phone in test_phones,
                    "last_inbound": row.last_inbound,
                    "last_message": recent.content if recent else "No messages yet",
                    "preferences": preferences,
                    "preference_sources": evidence,
                    "confirmed_budget": decode(budget.payload).get("amount_inr") if budget else None,
                    "proposals": [proposal_data(p) for p in proposals],
                }
            )
        return output

    @router.get("/dashboard")
    def overview(request: Request):
        with request.app.state.factory() as session:
            scalar = session.scalar
            visit_rows = list(
                session.scalars(
                    select(Proposal)
                    .where(Proposal.kind == "visit")
                    .order_by(Proposal.created.desc())
                    .limit(50)
                )
            )
            visits = []
            for row in visit_rows:
                item = proposal_data(row)
                buyer = session.get(Customer, row.phone)
                property_row = session.get(Property, item["details"].get("property_id", ""))
                item.update(
                    {
                        "buyer_name": buyer.name or "Buyer " + row.phone[-4:] if buyer else row.phone,
                        "property_title": property_row.title
                        if property_row
                        else item["details"].get("property_id"),
                        "location": ", ".join(filter(None, [property_row.locality, property_row.city]))
                        if property_row
                        else "",
                        "test": session.get(TestSession, row.phone) is not None,
                    }
                )
                visits.append(item)
            return {
                "counts": {
                    "conversations": scalar(select(func.count()).select_from(Customer)),
                    "properties": scalar(select(func.count()).select_from(Property)),
                    "visit_requests": scalar(
                        select(func.count())
                        .select_from(Proposal)
                        .where(
                            Proposal.kind == "visit",
                            Proposal.status.in_(["pending_confirmation", "requested"]),
                        )
                    ),
                    "visits_awaiting_buyer": scalar(
                        select(func.count())
                        .select_from(Proposal)
                        .where(Proposal.kind == "visit", Proposal.status == "pending_confirmation")
                    ),
                    "visits_awaiting_dealer": scalar(
                        select(func.count())
                        .select_from(Proposal)
                        .where(Proposal.kind == "visit", Proposal.status == "requested")
                    ),
                    "human_followups": scalar(
                        select(func.count())
                        .select_from(Customer)
                        .where(Customer.paused.is_(True), Customer.opted_out.is_(False))
                    ),
                    "messages": scalar(select(func.count()).select_from(Message)),
                },
                "customers": customers(session),
                "visits": visits,
                "alerts": [
                    {"id": a.id, "phone": a.phone, "detail": a.detail, "created": a.created}
                    for a in session.scalars(
                        select(Audit)
                        .where(Audit.action == "dealer_alert")
                        .order_by(Audit.created.desc())
                        .limit(50)
                    )
                ],
            }

    @router.get("/conversations")
    def list_conversations(request: Request):
        with request.app.state.factory() as session:
            return customers(session)

    @router.get("/conversations/{phone}/activity")
    def activity(phone: str, request: Request):
        with request.app.state.factory() as session:
            if not session.get(Customer, phone):
                raise HTTPException(404, "Conversation not found")
            return [
                {"id": a.id, "action": a.action, "detail": a.detail, "created": a.created}
                for a in session.scalars(
                    select(Audit).where(Audit.phone == phone).order_by(Audit.created.desc()).limit(100)
                )
            ]

    @router.get("/conversations/{phone}/recommendations")
    def recommendations(phone: str, request: Request):
        with request.app.state.factory() as session:
            customer = session.get(Customer, phone)
            if not customer:
                raise HTTPException(404, "Conversation not found")
            searches = list(
                session.scalars(
                    select(Audit)
                    .where(Audit.phone == phone, Audit.action == "property_search_results")
                    .order_by(Audit.created.desc())
                    .limit(50)
                )
            )
            batches = []
            for search in reversed(searches):
                data = decode(search.detail)
                properties = []
                for property_id in data.get("property_ids", []):
                    row = session.get(Property, property_id)
                    if row and (not row.demo or settings.allow_demo_data):
                        properties.append(property_data(row))
                batches.append(
                    {
                        "source_message_id": data.get("source_message_id"),
                        "properties": properties,
                        "filters": data.get("filters", {}),
                    }
                )
            more_available = False
            if searches and not customer.paused and not customer.opted_out:
                args = SearchArgs.model_validate(
                    {**decode(searches[0].detail).get("filters", {}), "exclude_seen": True}
                )
                query = ToolService(session, phone, "preview", settings.allow_demo_data).search_query(args)
                more_available = session.scalar(query.limit(1)) is not None
            return {"batches": batches, "has_more": more_available, "has_search": bool(searches)}

    @router.post("/test-sessions/{phone}/more-properties", status_code=202)
    def more_properties(phone: str, request: Request):
        return queue_property_search(phone, request, "more")

    @router.post("/test-sessions/{phone}/browse-properties", status_code=202)
    def browse_properties(phone: str, request: Request):
        return queue_property_search(phone, request, "browse")

    def queue_property_search(phone, request, action):
        if settings.whatsapp_mode == "live":
            raise HTTPException(409, "Test recommendations require simulation mode")
        with request.app.state.factory() as session:
            customer = session.get(Customer, phone)
            if not session.get(TestSession, phone) or not customer:
                raise HTTPException(404, "Test conversation not found")
            if customer.paused or customer.opted_out:
                raise HTTPException(409, "This conversation is paused or opted out")
            if session.scalar(
                select(Job).where(Job.phone == phone, Job.state.in_(["pending", "processing"])).limit(1)
            ):
                raise HTTPException(409, "Wait for the current reply before requesting more properties")
        event_id = action + ":" + uuid4().hex
        enqueue(
            request.app.state.factory,
            event_id,
            phone,
            "Browse all available inventory across locations and budgets."
            if action == "browse"
            else "Show me more matching properties using the same search criteria.",
            "simulate",
        )
        return {"accepted": True, "event_id": event_id}

    @router.get("/jobs/{event_id:path}")
    def job_status(event_id: str, request: Request):
        with request.app.state.factory() as session:
            row = session.get(Job, event_id)
            if not row:
                raise HTTPException(404, "Job not found")
            return {"id": row.id, "state": row.state, "attempts": row.attempts, "error": row.error}

    @router.get("/test-sessions")
    def test_sessions(request: Request):
        with request.app.state.factory() as session:
            return [
                {"phone": s.phone, "name": s.name, "created": s.created}
                for s in session.scalars(select(TestSession).order_by(TestSession.created.desc()))
            ]

    @router.post("/test-sessions", status_code=201)
    def create_session(body: SessionInput, request: Request):
        if settings.whatsapp_mode == "live":
            raise HTTPException(409, "Switch to simulation mode before creating test conversations")
        phone = "999" + str(uuid4().int).zfill(12)[-12:]
        with request.app.state.factory() as session:
            row = TestSession(phone=phone, name=body.name)
            session.add(row)
            session.add(Customer(phone=phone, name=body.name))
            session.commit()
            return {"phone": phone, "name": row.name, "created": row.created}

    @router.post("/integrations/ollama/check")
    async def check_ollama():
        key = settings.ollama_api_key.get_secret_value()
        if settings.ollama_requires_api_key and not key:
            return {
                "reachable": False,
                "model_available": False,
                "message": "Remote endpoint needs an API key.",
            }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                result = await client.get(
                    settings.ollama_base_url + "/api/tags",
                    headers={"Authorization": f"Bearer {key}"} if key else {},
                )
                result.raise_for_status()
                names = [m.get("name", m.get("model")) for m in result.json().get("models", [])]
                available = settings.ollama_model in names
                return {
                    "reachable": True,
                    "model_available": available,
                    "message": "Endpoint reachable; configured model is listed."
                    if available
                    else "Endpoint reachable; configured model is not listed. Check the model name in Ollama.",
                    "note": "This checks connectivity and model listing, not inference or cloud sign-in.",
                }
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            return {
                "reachable": False,
                "model_available": False,
                "message": "Could not connect. Check that Ollama is running and the endpoint is correct.",
            }

    app.include_router(router)
