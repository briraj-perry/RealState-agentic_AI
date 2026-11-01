from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from estate_ai.db import Customer, Message, Property, Proposal
from estate_ai.main import create_app
from estate_ai.property_templates import templates
from estate_ai.tools import ToolService, confirm_proposal

HEADERS = {"X-API-Key": "test-admin-secret"}


def test_templates_are_fictional_and_seed_is_idempotent(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        assert client.get("/api/property-templates").status_code == 401
        catalog = client.get("/api/property-templates", headers=HEADERS).json()
        assert len(catalog) == 8
        assert all(row["demo"] for row in catalog)
        assert len({row["city"] for row in catalog}) == 5
        assert {row["bedrooms"] for row in catalog} == {1, 2, 3, 4}
        assert client.post("/api/demo/seed", headers=HEADERS).json()["created_count"] == 8
        assert client.post("/api/demo/seed", headers=HEADERS).json()["created_count"] == 0
        assert len(client.get("/api/properties", headers=HEADERS).json()) == 8


def test_demo_can_be_edited_but_not_promoted_to_real(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        client.post("/api/demo/seed", headers=HEADERS)
        sample = templates()[0]
        sample["asking_price"] = 8700000
        assert client.put("/api/properties/" + sample["id"], headers=HEADERS, json=sample).status_code == 200
        sample["demo"] = False
        assert client.put("/api/properties/" + sample["id"], headers=HEADERS, json=sample).status_code == 409
        client.post("/api/demo/seed", headers=HEADERS)
        rows = client.get("/api/properties", headers=HEADERS).json()
        assert next(row for row in rows if row["id"] == sample["id"])["asking_price_inr"] == 8700000


def test_demo_seed_requires_permission_and_is_blocked_live(factory, settings):
    sample = templates()[0]
    settings.allow_demo_data = False
    with TestClient(create_app(settings, factory)) as client:
        assert client.post("/api/demo/seed", headers=HEADERS).status_code == 409
        assert client.put("/api/properties/" + sample["id"], headers=HEADERS, json=sample).status_code == 409
    settings.allow_demo_data = True
    settings.whatsapp_mode = "live"
    with TestClient(create_app(settings, factory)) as client:
        assert client.post("/api/demo/seed", headers=HEADERS).status_code == 409
        assert client.put("/api/properties/" + sample["id"], headers=HEADERS, json=sample).status_code == 409


def test_agent_visit_is_visible_before_and_after_buyer_confirmation(factory, settings):
    phone = "919876543210"
    with factory() as session:
        session.add(Customer(phone=phone, name="Visit test buyer"))
        session.add(
            Property(
                id="p1",
                title="Test apartment",
                city="Mohali",
                locality="Sector 70",
                bedrooms=3,
                asking_price=8500000,
            )
        )
        session.add(Message(id="buyer-visit", phone=phone, role="user", content="Tomorrow at 4 PM"))
        session.flush()
        result = ToolService(session, phone, "buyer-visit").execute(
            "request_site_visit",
            {"property_id": "p1", "start_time": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
        )
        assert "proposal_id" in result
        session.commit()
    with TestClient(create_app(settings, factory)) as client:
        before = client.get("/api/dashboard", headers=HEADERS).json()
        assert before["counts"]["visit_requests"] == 1
        assert before["counts"]["visits_awaiting_buyer"] == 1
        assert before["counts"]["visits_awaiting_dealer"] == 0
        assert before["visits"][0]["status"] == "pending_confirmation"
        assert before["visits"][0]["buyer_name"] == "Visit test buyer"
        assert before["visits"][0]["property_title"] == "Test apartment"
        assert before["visits"][0]["location"] == "Sector 70, Mohali"
        with factory() as session:
            confirm_proposal(session, phone, "CONFIRM " + result["proposal_id"], "confirmation")
            session.commit()
        after = client.get("/api/dashboard", headers=HEADERS).json()
        assert after["counts"]["visit_requests"] == 1
        assert after["counts"]["visits_awaiting_buyer"] == 0
        assert after["counts"]["visits_awaiting_dealer"] == 1
        assert after["visits"][0]["status"] == "requested"
        with factory() as session:
            assert session.get(Proposal, result["proposal_id"]).confirmation_message_id == "confirmation"
