import json

import httpx
from fastapi.testclient import TestClient

from estate_ai.db import Audit, Customer, Proposal
from estate_ai.main import create_app

HEADERS = {"X-API-Key": "test-admin-secret"}


def test_dashboard_assets_and_read_models_require_auth(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        assert client.get("/").status_code == 200
        assert "Test Your Agent" in client.get("/assets/app.js").text
        assert client.get("/assets/styles.css").status_code == 200
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
        session.commit()
    with TestClient(create_app(settings, factory)) as client:
        data = client.get("/api/dashboard", headers=HEADERS).json()
        assert data["counts"]["human_followups"] == 1
        assert data["counts"]["visit_requests"] == 1
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
    with TestClient(create_app(settings, factory)) as client:
        data = client.post("/api/integrations/ollama/check", headers=HEADERS).json()
        assert data["reachable"] and data["model_available"]
        assert "not inference" in data["note"]
        status = client.get("/api/status", headers=HEADERS).json()
        assert status["whatsapp_mode"] == "simulate"
        assert not status["whatsapp_credentials_configured"]
        assert status["calendar"] == "not_connected"


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
