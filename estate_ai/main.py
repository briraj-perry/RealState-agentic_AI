import asyncio
import hashlib
import hmac
import json
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError
from pymongo.errors import DocumentTooLarge, DuplicateKeyError

from estate_ai.config import get_settings
from estate_ai.dashboard import register_dashboard
from estate_ai.db import (
    Audit,
    ConcurrentWriteError,
    Customer,
    Job,
    Message,
    Outbox,
    Property,
    Proposal,
    connect,
    now,
)
from estate_ai.document_query import select
from estate_ai.inventory_import import register_inventory_import
from estate_ai.photos import register_photos
from estate_ai.property_templates import seed_demo_inventory, templates
from estate_ai.schemas import ChatInput, PropertyInput, normalize_phone
from estate_ai.tools import property_data
from estate_ai.workflows import Worker, enqueue


def create_app(settings=None, factory=None, agent=None, whatsapp=None):
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.factory = factory or connect(
            settings.mongodb_uri.get_secret_value(), settings.mongodb_database
        )
        app.state.worker = Worker(app.state.factory, settings, agent, whatsapp)
        task = None
        if settings.worker_enabled:
            task = asyncio.create_task(app.state.worker.run())
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if factory is None:
            app.state.factory.close()

    app = FastAPI(
        title="Estate AI",
        version="0.1.0",
        lifespan=lifespan,
        description="Single-dealer WhatsApp agent. Visits are requests pending dealer approval.",
    )

    def admin(x_api_key: str = Header(default="")):
        expected = settings.admin_api_key.get_secret_value()
        if not expected or expected.startswith("replace-") or not hmac.compare_digest(expected, x_api_key):
            raise HTTPException(401, "A configured X-API-Key is required")

    @app.exception_handler(ConcurrentWriteError)
    @app.exception_handler(DuplicateKeyError)
    async def conflict(request, exc):
        return JSONResponse(
            status_code=409, content={"detail": "Data changed. Reload and retry the operation."}
        )

    @app.exception_handler(DocumentTooLarge)
    async def too_large(request, exc):
        return JSONResponse(
            status_code=413,
            content={"detail": "Import is too large for one document. Split the sheet into smaller files."},
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/status", dependencies=[Depends(admin)])
    def status():
        return {
            "model": settings.ollama_model,
            "ollama_configured": not settings.ollama_requires_api_key
            or bool(settings.ollama_api_key.get_secret_value()),
            "ollama_base_url": settings.ollama_base_url,
            "ollama_api_key_required": settings.ollama_requires_api_key,
            "whatsapp_mode": settings.whatsapp_mode,
            "calendar": "not_connected",
            "worker_enabled": settings.worker_enabled,
            "demo_inventory_allowed": settings.allow_demo_data,
            "business_name": settings.business_name,
            "timezone": "Asia/Kolkata",
            "whatsapp_credentials_configured": all(
                [
                    bool(settings.whatsapp_access_token.get_secret_value()),
                    settings.whatsapp_phone_number_id,
                    bool(settings.whatsapp_app_secret.get_secret_value()),
                    bool(settings.whatsapp_verify_token.get_secret_value()),
                    settings.whatsapp_graph_version,
                ]
            ),
            "ollama_api_key_configured": bool(settings.ollama_api_key.get_secret_value()),
            "database": "MongoDB",
        }

    @app.post("/api/simulator/messages", status_code=202, dependencies=[Depends(admin)])
    def simulate(body: ChatInput, request: Request):
        if settings.whatsapp_mode == "live":
            raise HTTPException(409, "Simulator disabled in live mode")
        key = f"sim:{body.event_id}"
        accepted = enqueue(request.app.state.factory, key, body.phone, body.text, "simulate")
        return {"event_id": key, "accepted": accepted}

    @app.get("/api/jobs", dependencies=[Depends(admin)])
    def jobs(request: Request):
        with request.app.state.factory() as session:
            return [
                {"id": j.id, "state": j.state, "attempts": j.attempts, "error": j.error}
                for j in session.scalars(select(Job).order_by(Job.created.desc()).limit(100))
            ]

    @app.get("/api/conversations/{phone}", dependencies=[Depends(admin)])
    def conversation(phone: str, request: Request):
        phone = valid_phone(phone)
        with request.app.state.factory() as session:
            customer = session.get(Customer, phone)
            if not customer:
                raise HTTPException(404, "Customer not found")
            recent = list(
                session.scalars(
                    select(Message).where(Message.phone == phone).order_by(Message.created.desc()).limit(200)
                )
            )
            return {
                "paused": customer.paused,
                "opted_out": customer.opted_out,
                "messages": [
                    {"id": m.id, "role": m.role, "content": m.content, "created": m.created}
                    for m in reversed(recent)
                ],
                "outbox": [
                    {"id": o.id, "state": o.state, "error": o.error}
                    for o in session.scalars(
                        select(Outbox).where(Outbox.phone == phone).order_by(Outbox.created.desc()).limit(100)
                    )
                ],
                "jobs": [
                    {"id": j.id, "state": j.state, "attempts": j.attempts, "error": j.error}
                    for j in session.scalars(
                        select(Job).where(Job.phone == phone).order_by(Job.created.desc()).limit(20)
                    )
                ],
            }

    @app.post("/api/conversations/{phone}/takeover", dependencies=[Depends(admin)])
    def takeover(phone: str, request: Request):
        return set_pause(request, phone, True)

    @app.post("/api/conversations/{phone}/resume", dependencies=[Depends(admin)])
    def resume(phone: str, request: Request):
        return set_pause(request, phone, False)

    def set_pause(request, phone, value):
        phone = valid_phone(phone)
        with request.app.state.factory() as session:
            customer = session.get(Customer, phone)
            if not customer:
                raise HTTPException(404, "Customer not found")
            if customer.opted_out and not value:
                raise HTTPException(409, "Opted-out contacts cannot be resumed by this endpoint")
            customer.paused = value
            if value:
                for item in session.scalars(
                    select(Outbox).where(Outbox.phone == phone, Outbox.state == "pending")
                ):
                    item.state = "suppressed"
                for job in session.scalars(select(Job).where(Job.phone == phone, Job.state == "pending")):
                    job.state = "suppressed"
            session.add(Audit(phone=phone, action="human_takeover" if value else "automation_resumed"))
            session.commit()
        return {"paused": value}

    @app.put("/api/properties/{property_id}", dependencies=[Depends(admin)])
    def upsert_property(property_id: str, body: PropertyInput, request: Request):
        if property_id != body.id:
            raise HTTPException(422, "Path and body property IDs must match")
        if body.demo and (not settings.allow_demo_data or settings.whatsapp_mode == "live"):
            raise HTTPException(409, "Demo inventory requires ALLOW_DEMO_DATA=true and simulation mode")
        with request.app.state.factory() as session:
            row = session.get(Property, property_id)
            if row is None:
                row = Property(**body.model_dump())
                session.add(row)
            else:
                if row.demo != body.demo:
                    raise HTTPException(409, "A property's demo/real classification cannot be changed")
                for key, value in body.model_dump().items():
                    setattr(row, key, value)
                row.verified_at = now()
            session.commit()
            return property_data(row, include_internal=True)

    @app.get("/api/properties", dependencies=[Depends(admin)])
    def properties(request: Request):
        with request.app.state.factory() as session:
            return [
                property_data(p, include_internal=True) for p in session.scalars(select(Property).limit(200))
            ]

    @app.post("/api/demo/seed", dependencies=[Depends(admin)])
    def seed(request: Request):
        if not settings.allow_demo_data or settings.whatsapp_mode == "live":
            raise HTTPException(409, "Demo seed requires ALLOW_DEMO_DATA=true and simulation mode")
        with request.app.state.factory() as session:
            created = seed_demo_inventory(session)
            session.commit()
        return {
            "demo": True,
            "property_id": "DEMO-MOHALI-001",
            "created": created,
            "created_count": len(created),
            "template_count": len(templates()),
        }

    @app.get("/api/property-templates", dependencies=[Depends(admin)])
    def property_templates():
        return templates()

    @app.get("/api/proposals", dependencies=[Depends(admin)])
    def proposals(request: Request):
        with request.app.state.factory() as session:
            return [
                {
                    "id": p.id,
                    "phone": p.phone,
                    "kind": p.kind,
                    "details": json.loads(p.payload),
                    "status": p.status,
                    "source_message_id": p.source_message_id,
                    "confirmation_message_id": p.confirmation_message_id,
                }
                for p in session.scalars(select(Proposal).order_by(Proposal.created.desc()).limit(200))
            ]

    @app.get("/api/alerts", dependencies=[Depends(admin)])
    def alerts(request: Request):
        with request.app.state.factory() as session:
            return [
                {"id": a.id, "phone": a.phone, "detail": a.detail, "created": a.created}
                for a in session.scalars(
                    select(Audit)
                    .where(Audit.action == "dealer_alert")
                    .order_by(Audit.created.desc())
                    .limit(100)
                )
            ]

    @app.get("/webhooks/whatsapp", response_class=PlainTextResponse)
    def verify(
        mode: str = Query("", alias="hub.mode"),
        token: str = Query("", alias="hub.verify_token"),
        challenge: str = Query("", alias="hub.challenge"),
    ):
        expected = settings.whatsapp_verify_token.get_secret_value()
        if mode != "subscribe" or not expected or not hmac.compare_digest(token, expected):
            raise HTTPException(403, "Webhook verification failed")
        return challenge

    @app.post("/webhooks/whatsapp")
    async def webhook(request: Request, x_hub_signature_256: str = Header(default="")):
        if settings.whatsapp_mode != "live":
            raise HTTPException(409, "WhatsApp webhook delivery requires live mode")
        # Bound the body before accumulating it; don't trust Content-Length alone.
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 1_000_000:
                raise HTTPException(413, "Webhook body too large")
            chunks.append(chunk)
        body = b"".join(chunks)
        secret = settings.whatsapp_app_secret.get_secret_value()
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(signature, x_hub_signature_256):
            raise HTTPException(403, "Invalid webhook signature")
        try:
            payload = json.loads(body)
            if payload.get("object") != "whatsapp_business_account":
                raise ValueError("Unexpected object")
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    if value.get("metadata", {}).get("phone_number_id") != settings.whatsapp_phone_number_id:
                        continue
                    for msg in value.get("messages", []):
                        if msg.get("type") != "text":
                            # This milestone supports text only. Surface unsupported input to dealer.
                            with request.app.state.factory() as session:
                                session.add(
                                    Audit(
                                        phone=normalize_phone(msg["from"]),
                                        action="dealer_alert",
                                        detail="Unsupported WhatsApp message type",
                                    )
                                )
                                session.commit()
                            continue
                        parsed = ChatInput(phone=msg["from"], text=msg["text"]["body"], event_id=msg["id"])
                        enqueue(
                            request.app.state.factory,
                            "wa:" + parsed.event_id,
                            parsed.phone,
                            parsed.text,
                            "whatsapp",
                            float(msg["timestamp"]),
                        )
                    with request.app.state.factory() as session:
                        for update in value.get("statuses", []):
                            item = session.scalar(select(Outbox).where(Outbox.provider_id == update["id"]))
                            ranks = {"accepted": 0, "sent": 1, "delivered": 2, "read": 3}
                            state = update.get("status")
                            if item and (
                                state == "failed" or ranks.get(state, -1) > ranks.get(item.state, -1)
                            ):
                                item.state = state
                        session.commit()
        except (ValueError, TypeError, KeyError, AttributeError, ValidationError):
            raise HTTPException(400, "Malformed webhook event") from None
        return {"received": True}

    register_inventory_import(app, settings, admin)
    register_photos(app, settings, admin)
    register_dashboard(app, settings, admin)
    return app


def valid_phone(value):
    try:
        return normalize_phone(value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


app = create_app()
