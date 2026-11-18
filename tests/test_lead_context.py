import json

import pytest
from fastapi.testclient import TestClient

from estate_ai.agent import EstateAgent
from estate_ai.db import Message, Outbox, Property
from estate_ai.document_query import select
from estate_ai.main import create_app
from estate_ai.property_templates import templates
from estate_ai.workflows import Worker, enqueue

HEADERS = {"X-API-Key": "test-admin-secret"}


def test_catalog_has_stable_unique_references_and_separate_area_and_rug():
    catalog = templates()
    assert catalog == templates()
    assert len(catalog) == 500
    assert len({p["id"] for p in catalog}) == 500
    assert len({p["details"]["housing_listing_id"] for p in catalog}) == 500
    for p in catalog:
        assert p["demo"] and "Fictional" in p["description"]
        assert p["details"]["housing_listing_id"].startswith("DEMO-")
        assert int(p["details"]["carpet_area_sqft"]) < int(p["details"]["built_up_area_sqft"])
        assert "6 × 4 ft" in p["details"]["decorative_rug"]
        assert "Not verified" in p["details"]["rera_registration"]


def test_property_session_materializes_only_selected_template_and_resolves_listing(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        item = templates()[499]
        assert client.post("/api/test-sessions", json={"property_id": item["id"]}).status_code == 401
        lead = client.post(
            "/api/test-sessions",
            headers=HEADERS,
            json={"name": "Rahul enquiry", "buyer_name": "Rahul", "property_id": item["id"]},
        ).json()
        assert lead["property_id"] == item["id"]
        ref = item["details"]["housing_listing_id"]
        assert lead["listing_id"] == ref
        assert client.get("/api/housing-listings/" + ref, headers=HEADERS).json()["property_id"] == item["id"]
        assert len(client.get("/api/properties", headers=HEADERS).json()) == 1
        mapped = client.post(
            "/api/test-sessions", headers=HEADERS, json={"buyer_name": "Asha", "listing_id": ref}
        ).json()
        assert mapped["property_id"] == item["id"]
        assert mapped["phone"] != lead["phone"]
        assert (
            client.post("/api/test-sessions", headers=HEADERS, json={"listing_id": "unknown"}).status_code
            == 404
        )
        assert (
            client.post(
                "/api/test-sessions", headers=HEADERS, json={"listing_id": ref, "property_id": "different"}
            ).status_code
            == 422
        )
        assert (
            client.put(
                "/api/housing-listings/12345", headers=HEADERS, json={"property_id": item["id"]}
            ).status_code
            == 422
        )
        second = client.post(
            "/api/test-sessions", headers=HEADERS, json={"property_id": templates()[0]["id"]}
        ).json()
        assert (
            client.put(
                "/api/housing-listings/" + ref, headers=HEADERS, json={"property_id": second["property_id"]}
            ).status_code
            == 409
        )
        with factory() as session:
            session.get(Property, item["id"]).available = False
            session.commit()
        assert client.post("/api/test-sessions", headers=HEADERS, json={"listing_id": ref}).status_code == 409


def test_demo_context_is_blocked_without_permission_and_live(factory, settings):
    settings.allow_demo_data = False
    with TestClient(create_app(settings, factory)) as client:
        assert (
            client.post(
                "/api/test-sessions", headers=HEADERS, json={"property_id": templates()[0]["id"]}
            ).status_code
            == 404
        )
    settings.whatsapp_mode = "live"
    with TestClient(create_app(settings, factory)) as client:
        assert (
            client.post(
                "/api/test-sessions", headers=HEADERS, json={"property_id": templates()[0]["id"]}
            ).status_code
            == 409
        )


@pytest.mark.asyncio
async def test_hi_has_context_followup_gets_current_facts_and_handoff_summary(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        lead = client.post(
            "/api/test-sessions",
            headers=HEADERS,
            json={"name": "Rahul", "buyer_name": "Rahul", "property_id": templates()[0]["id"]},
        ).json()
        other = client.post(
            "/api/test-sessions",
            headers=HEADERS,
            json={"name": "Asha", "buyer_name": "Asha", "property_id": templates()[1]["id"]},
        ).json()

    class Model:
        async def chat(self, messages, tools):
            assert messages[-2]["role"] == "assistant"
            assert messages[-2]["tool_calls"][0]["function"]["name"] == "get_property_details"
            assert messages[-1]["role"] == "tool"
            context = json.loads(next(m["content"] for m in messages if m["role"] == "tool"))["lead_context"]
            assert context["buyer_name"] == "Rahul"
            assert context["property"]["asking_price_inr"] == 9100000
            assert context["property"]["id"] == lead["property_id"]
            assert "Asha" not in json.dumps(messages)
            return {
                "role": "assistant",
                "content": "The asking price is ₹91 lakh; Biba must approve any offer.",
            }

    worker = Worker(factory, settings, agent=EstateAgent(settings, Model()))
    for prefix, row in [("rahul", lead), ("asha", other)]:
        enqueue(factory, prefix + "-hi", row["phone"], "Hi", "simulate")
        await worker.tick()
    with factory() as session:
        reply = session.get(Message, "reply:rahul-hi").content
        assert "Hi Rahul" in reply and "AI assistant for Hukam Realators" in reply
        assert lead["property_id"] in reply and "fictional" in reply
        assert "Hi Asha" in session.get(Message, "reply:asha-hi").content
        assert session.get(Outbox, "rahul-hi").state == "simulated"
        session.get(Property, lead["property_id"]).asking_price = 9100000
        session.commit()
    enqueue(factory, "rahul-price", lead["phone"], "What is the price?", "simulate")
    await worker.tick()
    with factory() as session:
        assert "91 lakh" in session.get(Message, "reply:rahul-price").content
    enqueue(factory, "rahul-human", lead["phone"], "talk to Biba", "simulate")
    with TestClient(create_app(settings, factory)) as client:
        conversation = client.get("/api/conversations/" + lead["phone"], headers=HEADERS).json()
        assert conversation["paused"]
        activity = client.get("/api/conversations/" + lead["phone"] + "/activity", headers=HEADERS).json()
        summary = json.loads(next(a["detail"] for a in activity if a["action"] == "dealer_alert"))
        assert summary["buyer_name"] == "Rahul"
        assert summary["property_id"] == lead["property_id"]
        assert any("91 lakh" in m["text"] for m in summary["recent_messages"])
    with factory() as session:
        assert not list(session.scalars(select(Outbox).where(Outbox.channel == "whatsapp")))
