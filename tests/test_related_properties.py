import json

import pytest
from fastapi.testclient import TestClient

from estate_ai.agent import EstateAgent
from estate_ai.db import Customer, Message, Property, Proposal
from estate_ai.db import TestSession as BuyerSession
from estate_ai.main import create_app
from estate_ai.schemas import RelatedArgs
from estate_ai.tools import ToolService

HEADERS = {"X-API-Key": "test-admin-secret"}
PHONE = "999123456789001"


@pytest.fixture
def related_factory(factory):
    with factory() as session:
        session.add(Customer(phone=PHONE, name="Rahul"))
        session.add(BuyerSession(phone=PHONE, name="Related homes", buyer_name="Rahul", property_id="anchor"))
        session.add(Message(id="related-source", phone=PHONE, role="user", content="Related homes please"))
        for identity, price, locality, overrides in [
            ("anchor", 10000000, "Sector 70", {}),
            ("same-near", 10100000, "Sector 70", {}),
            ("same-far", 11000000, "Sector 70", {}),
            ("other-cheap", 9800000, "Sector 79", {}),
            ("other-near", 10050000, "Sector 79", {}),
            ("other-low", 8500000, "Sector 80", {}),
            ("sold", 10000000, "Sector 70", {"available": False}),
            ("wrong-city", 10000000, "Sector 70", {"city": "Zirakpur"}),
            ("wrong-bhk", 10000000, "Sector 70", {"bedrooms": 2}),
            ("too-expensive", 12000001, "Sector 70", {}),
            ("too-cheap", 7999999, "Sector 70", {}),
            ("fictional", 10000000, "Sector 70", {"demo": True}),
        ]:
            session.add(
                Property(
                    **{
                        "id": identity,
                        "title": identity,
                        "city": "Mohali",
                        "locality": locality,
                        "bedrooms": 3,
                        "asking_price": price,
                        **overrides,
                    }
                )
            )
        session.commit()
    return factory


def test_related_ranking_availability_classification_seen_and_budget(related_factory):
    with related_factory() as session:
        tools = ToolService(session, PHONE, "related-source", True)
        first = tools.execute("find_related_properties", {})
        assert [p["id"] for p in first["properties"]] == ["same-near", "same-far", "other-near"]
        assert first["has_more"]
        assert "higher" in first["properties"][0]["match_note"]
        assert "Different locality" in first["properties"][2]["match_note"]
        second = tools.execute("find_related_properties", {})
        assert {p["id"] for p in second["properties"]} == {"other-cheap", "other-low"}
        assert not second["has_more"]
        assert tools.execute("find_related_properties", {})["properties"] == []
        session.add(Customer(phone="999123456789002"))
        other = ToolService(session, "999123456789002", "other-buyer", True)
        other_result = other.execute("find_related_properties", {"property_id": "anchor"})
        assert [p["id"] for p in other_result["properties"]] == [p["id"] for p in first["properties"]]
        # A pending but explicitly stated budget is still an upper bound for suggestions.
        session.add(
            Proposal(
                phone=PHONE,
                kind="budget",
                payload=json.dumps({"amount_inr": 10000000}),
                source_message_id="related-source",
            )
        )
        capped = tools.execute("find_related_properties", {"exclude_seen": False})
        assert {p["id"] for p in capped["properties"]} == {"other-cheap", "other-low"}
        assert all(p["asking_price_inr"] <= 10000000 for p in capped["properties"])
        # Reading the has-more preview must not mark any properties as seen.
        count = len(session.records)
        tools.related_candidates(RelatedArgs(exclude_seen=False))
        assert len(session.records) == count
        session.add(
            Proposal(
                phone=PHONE,
                kind="budget",
                payload=json.dumps({"amount_inr": 7000000}),
                source_message_id="related-source",
            )
        )
        reply = tools.related_properties()
        assert "below the similar-price range" in reply and "haven't shown above-budget homes" in reply


def test_related_errors_and_paused_guard(related_factory):
    with related_factory() as session:
        tools = ToolService(session, PHONE, "related-source")
        assert "error" in tools.execute("find_related_properties", {"limit": 6})
        assert "error" in tools.execute("find_related_properties", {"property_id": "missing"})
        assert "error" in tools.execute("find_related_properties", {"property_id": "fictional"})
        session.get(Customer, PHONE).paused = True
        assert tools.execute("find_related_properties", {}) == {
            "error": "Automation is paused or contact opted out"
        }


@pytest.mark.asyncio
async def test_auto_related_cards_and_more_button_use_real_inventory_without_model(related_factory, settings):
    class NoModel:
        async def chat(self, *args):
            raise AssertionError("Greeting and related buttons should not require model inference")

    with TestClient(create_app(settings, related_factory, agent=EstateAgent(settings, NoModel()))) as client:
        assert client.post(f"/api/test-sessions/{PHONE}/related-properties").status_code == 401
        queued = client.post(
            "/api/simulator/messages",
            headers=HEADERS,
            json={"phone": PHONE, "text": "Hi", "event_id": "related-hi"},
        ).json()
        await client.app.state.worker.tick()
        assert client.get("/api/jobs/" + queued["event_id"], headers=HEADERS).json()["state"] == "done"
        result = client.get(f"/api/conversations/{PHONE}/recommendations", headers=HEADERS).json()
        assert result["batches"][0]["kind"] == "selected"
        assert result["batches"][0]["properties"][0]["id"] == "anchor"
        assert result["batches"][1]["kind"] == "related"
        assert len(result["batches"][1]["properties"]) == 3
        assert result["has_more"]
        assert "match_note" in result["batches"][1]["properties"][0]
        job = client.post(f"/api/test-sessions/{PHONE}/related-properties", headers=HEADERS)
        assert job.status_code == 202
        assert (
            client.post(f"/api/test-sessions/{PHONE}/related-properties", headers=HEADERS).status_code == 409
        )
        await client.app.state.worker.tick()
        result = client.get(f"/api/conversations/{PHONE}/recommendations", headers=HEADERS).json()
        assert len(result["batches"][-1]["properties"]) == 2 and not result["has_more"]
        client.post(
            "/api/simulator/messages",
            headers=HEADERS,
            json={"phone": PHONE, "text": "show similar properties", "event_id": "related-empty"},
        )
        await client.app.state.worker.tick()
        conversation = client.get(f"/api/conversations/{PHONE}", headers=HEADERS).json()
        assert "haven't widened" in conversation["messages"][-1]["content"]
        assert all(o["state"] == "simulated" for o in conversation["outbox"])
        session = next(
            s for s in client.get("/api/test-sessions", headers=HEADERS).json() if s["phone"] == PHONE
        )
        assert session["property_id"] == "anchor"
        client.post(f"/api/conversations/{PHONE}/takeover", headers=HEADERS)
        assert (
            client.post(f"/api/test-sessions/{PHONE}/related-properties", headers=HEADERS).status_code == 409
        )
        settings.whatsapp_mode = "live"
        assert (
            client.post(f"/api/test-sessions/{PHONE}/related-properties", headers=HEADERS).status_code == 409
        )
