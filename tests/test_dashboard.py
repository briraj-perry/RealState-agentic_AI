import json
from datetime import timedelta

import httpx
from fastapi.testclient import TestClient

from estate_ai import apple_calendar
from estate_ai.db import Audit, Customer, Property, PropertyMetadata, Proposal
from estate_ai.main import create_app
from estate_ai.schemas import visit_tomorrow

HEADERS = {"X-API-Key": "test-admin-secret"}


def test_dashboard_assets_and_read_models_require_auth(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        assert client.get("/").status_code == 200
        assert "Test Your Agent" in client.get("/assets/app.js").text
        assert client.get("/assets/styles.css").status_code == 200
        manifest = client.get("/manifest.webmanifest")
        assert manifest.headers["content-type"] == "application/manifest+json"
        assert manifest.json()["display"] == "standalone"
        for icon in manifest.json()["icons"]:
            assert client.get(icon["src"]).headers["content-type"] == "image/png"
        assert client.get("/api/dashboard").status_code == 401
        assert client.get("/api/conversations").status_code == 401
        assert client.get("/api/test-sessions").status_code == 401
        assert client.post("/api/integrations/ollama/check").status_code == 401
        response = client.get("/api/dashboard", headers=HEADERS).json()
        assert response["counts"]["conversations"] == 0
        assert response["counts"]["visit_requests"] == 0
        assert response["customers"] == []


def test_test_session_is_saved_and_uses_existing_simulator(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        session = client.post("/api/test-sessions", headers=HEADERS, json={"name": "Mohali test"})
        assert session.status_code == 201
        phone = session.json()["phone"]
        assert client.get("/api/test-sessions", headers=HEADERS).json()[0]["phone"] == phone
        customers = client.get("/api/conversations", headers=HEADERS).json()
        assert customers[0]["test"]
        assert customers[0]["name"] == "Mohali test"
        queued = client.post(
            "/api/simulator/messages",
            headers=HEADERS,
            json={"phone": phone, "text": "Hi", "event_id": "dashboard-test"},
        ).json()
        job = client.get("/api/jobs/" + queued["event_id"], headers=HEADERS).json()
        assert job["state"] == "pending"
        assert (
            client.get("/api/conversations/" + phone, headers=HEADERS).json()["messages"][0]["content"]
            == "Hi"
        )


def test_overview_requirements_confirmations_and_followups(factory, settings):
    with factory() as session:
        session.add(Customer(phone="919876543210", name="Buyer", paused=True))
        session.add(Customer(phone="919876543211", opted_out=True, paused=True))
        session.add(
            Audit(
                phone="919876543210",
                action="preferences",
                detail=json.dumps(
                    {"values": {"location": "Mohali", "bedrooms": 3}, "source_message_id": "msg1"}
                ),
            )
        )
        session.add(
            Proposal(
                phone="919876543210",
                kind="budget",
                payload=json.dumps({"amount_inr": 9000000}),
                source_message_id="msg2",
                status="buyer_confirmed",
                confirmation_message_id="msg3",
            )
        )
        session.add(
            Proposal(
                phone="919876543210",
                kind="visit",
                payload=json.dumps({"property_id": "p1"}),
                source_message_id="msg4",
                status="requested",
            )
        )
        session.add(
            Property(
                id="p1", title="Apartment", city="Mohali", bedrooms=3, asking_price=8500000, available=False
            )
        )
        session.add(
            PropertyMetadata(property_id="p1", payload=json.dumps({"details": {"address": "1 Main Road"}}))
        )
        session.commit()
    with TestClient(create_app(settings, factory)) as client:
        data = client.get("/api/dashboard", headers=HEADERS).json()
        assert data["counts"]["human_followups"] == 1
        assert data["counts"]["visit_requests"] == 1
        visit = data["visits"][0]
        assert visit["address"] == "1 Main Road"
        assert visit["location"] == "Mohali"
        assert visit["property_available"] is False
        buyer = next(row for row in data["customers"] if row["name"] == "Buyer")
        assert buyer["preferences"]["location"] == "Mohali"
        assert buyer["confirmed_budget"] == 9000000
        assert buyer["preference_sources"] == ["msg1"]
        activity = client.get("/api/conversations/919876543210/activity", headers=HEADERS).json()
        assert activity[0]["action"] == "preferences"


def test_properties_can_be_created_and_updated_from_dashboard(factory, settings):
    listing = {"id": "p1", "title": "Apartment", "city": "Mohali", "bedrooms": 3, "asking_price": 8500000}
    with TestClient(create_app(settings, factory)) as client:
        assert client.put("/api/properties/p1", headers=HEADERS, json=listing).status_code == 200
        listing["asking_price"] = 8900000
        listing["available"] = False
        updated = client.put("/api/properties/p1", headers=HEADERS, json=listing).json()
        assert updated["asking_price_inr"] == 8900000
        assert not updated["available"]


def test_live_mode_cannot_create_simulated_test_session(factory, settings):
    settings.whatsapp_mode = "live"
    with TestClient(create_app(settings, factory)) as client:
        assert client.post("/api/test-sessions", headers=HEADERS, json={}).status_code == 409


def test_ollama_connection_check_reports_listing_without_claiming_inference(factory, settings, monkeypatch):
    def handler(request):
        assert str(request.url) == "http://localhost:11434/api/tags"
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"models": [{"name": "gemma4:31b-cloud"}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(apple_calendar, "available", lambda: False)
    with TestClient(create_app(settings, factory)) as client:
        data = client.post("/api/integrations/ollama/check", headers=HEADERS).json()
        assert data["reachable"] and data["model_available"]
        assert "not inference" in data["note"]
        status = client.get("/api/status", headers=HEADERS).json()
        assert status["whatsapp_mode"] == "simulate"
        assert not status["whatsapp_credentials_configured"]
        assert status["calendar"] == "not_connected"


def test_dashboard_calendar_enforces_tomorrow_and_returns_existing_save(factory, settings, monkeypatch):
    tomorrow = visit_tomorrow()
    with factory() as session:
        for proposal_id, day in (("today", tomorrow - timedelta(days=1)), ("tomorrow", tomorrow)):
            session.add(
                Proposal(
                    id=proposal_id,
                    phone="919876543210",
                    kind="visit",
                    source_message_id="msg",
                    payload=json.dumps({"property_id": "p1", "start_time": f"{day}T16:00:00+05:30"}),
                )
            )
        session.commit()

    saved = []

    def add_visit(row, title):
        saved.append((row.id, title))
        return {"status": "added"}

    monkeypatch.setattr(apple_calendar, "add_visit", add_visit)
    with TestClient(create_app(settings, factory)) as client:
        visits = client.get("/api/dashboard", headers=HEADERS).json()["visits"]
        assert {v["id"]: v["can_add_to_calendar"] for v in visits} == {"today": False, "tomorrow": True}
        assert client.post("/api/visits/today/apple-calendar", headers=HEADERS).status_code == 422
        url = "/api/visits/tomorrow/apple-calendar"
        assert client.post(url, headers=HEADERS).json() == {"status": "added"}
        assert client.post(url, headers=HEADERS).json() == {"status": "already_added"}
    assert saved == [("tomorrow", "p1")]


def test_ollama_connection_check_handles_unreachable_server(factory, settings, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("No Ollama", request=request)

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    with TestClient(create_app(settings, factory)) as client:
        data = client.post("/api/integrations/ollama/check", headers=HEADERS).json()
        assert not data["reachable"]
        assert not data["model_available"]
