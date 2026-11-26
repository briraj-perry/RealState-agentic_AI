import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from estate_ai.agent import EstateAgent
from estate_ai.db import Customer, Message, Outbox, Property
from estate_ai.document_query import select
from estate_ai.main import create_app
from estate_ai.property_templates import templates
from estate_ai.workflows import Worker, enqueue

HEADERS = {"X-API-Key": "test-admin-secret"}


def test_catalog_has_stable_unique_references_and_separate_area_and_rug():
    catalog = templates()
    assert catalog == templates()
    assert len(catalog) == 800
    assert len({p["id"] for p in catalog}) == 800
    assert len({p["details"]["housing_listing_id"] for p in catalog}) == 800
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


@pytest.mark.asyncio
async def test_portal_interest_then_budget_then_yes(factory, settings):
    from estate_ai.db import Proposal

    item = templates()[0]
    with TestClient(create_app(settings, factory)) as client:
        res = client.post(
            "/api/test-sessions",
            headers=HEADERS,
            json={
                "name": "Buyer test",
                "buyer_name": "Sam",
                "property_id": item["id"],
                "portal_interest": True,
            },
        )
        assert res.status_code == 201
        phone = res.json()["phone"]
        cards = client.get(f"/api/conversations/{phone}/recommendations", headers=HEADERS).json()
        assert not cards["has_search"]
        (welcome,) = cards["batches"]
        assert welcome["message_id"] == f"welcome:{phone}" and welcome["kind"] == "selected"
        assert [p["id"] for p in welcome["properties"]] == [item["id"]]
    with factory() as session:
        assert "Hi Sam" in session.get(Message, "welcome:" + phone).content
    worker = Worker(factory, settings)
    for event, text in [("budget-test", "my budget is 90 lakh"), ("yes-test", "yes")]:
        assert enqueue(factory, event, phone, text, "simulate")
        await worker.tick()
    with factory() as session:
        reply = session.get(Message, "reply:budget-test").content
        assert reply.index(item["title"]) < reply.index("Should I confirm")
        budget = session.scalar(select(Proposal).where(Proposal.phone == phone))
        assert budget.status == "buyer_confirmed" and budget.confirmation_message_id == "yes-test"
        assert json.loads(budget.payload) == {
            "amount_inr": 9000000,
            "kind": "budget",
            "property_id": item["id"],
        }


@pytest.mark.asyncio
async def test_live_portal_sends_one_template_before_buyer_replies(factory, settings, monkeypatch):
    settings.whatsapp_mode = "live"
    settings.allow_demo_data = False
    settings.whatsapp_interest_template = "property_enquiry"
    settings.whatsapp_interest_template_language = "en_US"
    settings.whatsapp_phone_number_id = "123"
    settings.whatsapp_graph_version = "v26.0"
    event = {
        "event_id": str(uuid4()),
        "phone": "+91 98765 43210",
        "buyer_name": "Sam",
        "property_id": "home-1",
        "whatsapp_consent": True,
    }
    phone = "919876543210"
    with factory() as session:
        session.add(
            Property(id="home-1", title="Sector 70 flat", city="Mohali", bedrooms=3, asking_price=8500000)
        )
        session.add(
            Property(id="demo", title="Demo flat", city="Mohali", bedrooms=3, asking_price=8500000, demo=True)
        )
        session.commit()
    with TestClient(create_app(settings, factory)) as client:
        path = "/api/property-interests"
        assert client.post(path, json=event).status_code == 401
        assert (
            client.post(path, json={**event, "whatsapp_consent": False}, headers=HEADERS).status_code == 422
        )
        assert client.post(path, json={**event, "property_id": "demo"}, headers=HEADERS).status_code == 404
        queued = client.post(path, json=event, headers=HEADERS)
        assert queued.status_code == 202
        assert queued.json()["state"] == "pending"
        assert client.post(path, json=event, headers=HEADERS).json() == queued.json()
        assert client.post(path, json={**event, "buyer_name": "Lee"}, headers=HEADERS).status_code == 409
        cancelled = client.post(
            path, json={**event, "event_id": str(uuid4()), "phone": "919876543211"}, headers=HEADERS
        ).json()["event_id"]
    assert enqueue(factory, "wa:stop", "919876543211", "STOP", "whatsapp")

    requests = []

    def send(request):
        requests.append(json.loads(request.content))
        assert request.url.path == "/v26.0/123/messages"
        return httpx.Response(200, json={"messages": [{"id": "wamid.interest"}]})

    worker = Worker(factory, settings)
    async_client = httpx.AsyncClient
    with monkeypatch.context() as patch:
        patch.setattr(
            httpx,
            "AsyncClient",
            lambda **options: async_client(transport=httpx.MockTransport(send), **options),
        )
        await worker.send_one()
        await worker.send_one()
        await worker.send_one()

    (sent,) = requests
    assert sent["to"] == phone and sent["type"] == "template"
    assert sent["template"]["language"] == {"code": "en_US"}
    assert sent["template"]["name"] == "property_enquiry"
    assert [p["text"] for p in sent["template"]["components"][0]["parameters"]] == [
        "Sam",
        settings.business_name,
        "Sector 70 flat",
    ]
    with factory() as session:
        assert session.get(Customer, phone).last_inbound == 0
        assert session.get(Customer, phone).interest_property_id == "home-1"
        item = session.get(Outbox, queued.json()["event_id"])
        assert (item.state, item.provider_id) == ("accepted", "wamid.interest")
        assert session.get(Outbox, cancelled).state == "suppressed"

    class FollowupModel:
        async def chat(self, messages, tools):
            context = next(json.loads(m["content"])["lead_context"] for m in messages if m["role"] == "tool")
            assert context["buyer_name"] == "Sam"
            assert context["property"]["id"] == "home-1"
            return {"role": "assistant", "content": "The Sector 70 flat is listed at ₹85 lakh."}

    assert enqueue(factory, "wa:followup", phone, "How much is it?", "whatsapp")
    await Worker(factory, settings, agent=EstateAgent(settings, FollowupModel())).process_one()
    with factory() as session:
        followup = session.get(Outbox, "wa:followup")
        assert followup.body == "The Sector 70 flat is listed at ₹85 lakh."
        assert followup.template is None
