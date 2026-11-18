import pytest
from fastapi.testclient import TestClient

from estate_ai.agent import EstateAgent
from estate_ai.db import Customer, Job, Message, Outbox, now
from estate_ai.main import create_app
from estate_ai.workflows import Worker, enqueue

HEADERS = {"X-API-Key": "test-admin-secret"}


class NoWhatsApp:
    async def send(self, *args):
        raise AssertionError("A synthetic conversation must never send to WhatsApp")


def test_buyer(client, factory):
    lead = client.post(
        "/api/test-sessions", headers=HEADERS, json={"buyer_name": "Rahul", "property_id": "DEMO-MOHALI-001"}
    ).json()
    enqueue(factory, "buyer-handoff", lead["phone"], "human", "simulate")
    return lead["phone"]


test_buyer.__test__ = False


@pytest.mark.asyncio
async def test_human_reply_stays_paused_is_idempotent_and_moves_work_queue(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        phone = test_buyer(client, factory)
        queue = client.get("/api/dashboard", headers=HEADERS).json()
        assert next(c for c in queue["customers"] if c["phone"] == phone)["reply_needed"]
        with factory() as session:
            session.add(Outbox(id="stale-ai", phone=phone, body="Old AI reply", channel="simulate"))
            session.add(Job(id="stale-job", phone=phone, text="Old question", channel="simulate"))
            session.commit()
        # Pre-upgrade outbox documents have no sender field and must also be cancelled.
        legacy = Outbox(id="legacy-ai", phone=phone, body="Legacy AI reply", channel="simulate").values()
        del legacy["sender"]
        factory.database[Outbox.collection].insert_one({"_id": "legacy-ai", "_revision": 1, **legacy})
        payload = {"text": "Hello Rahul, our team can check the documents for you.", "event_id": "reply-1"}
        assert client.post(f"/api/conversations/{phone}/reply", json=payload).status_code == 401
        result = client.post(f"/api/conversations/{phone}/reply", headers=HEADERS, json=payload)
        assert result.status_code == 202
        assert result.json()["channel"] == "simulate"
        queued_buyer = next(
            c
            for c in client.get("/api/dashboard", headers=HEADERS).json()["customers"]
            if c["phone"] == phone
        )
        assert queued_buyer["followup_status"] == "reply_queued"
        assert (
            client.post(f"/api/conversations/{phone}/reply", headers=HEADERS, json=payload).status_code == 202
        )
        assert (
            client.post(
                f"/api/conversations/{phone}/reply",
                headers=HEADERS,
                json={**payload, "text": "different message"},
            ).status_code
            == 409
        )
        await Worker(factory, settings, whatsapp=NoWhatsApp()).send_one()
        conversation = client.get(f"/api/conversations/{phone}", headers=HEADERS).json()
        assert conversation["paused"]
        human = [m for m in conversation["messages"] if m["author"] == "human"]
        assert len(human) == 1 and human[0]["content"] == payload["text"]
        assert next(o for o in conversation["outbox"] if o["id"] == "human:reply-1")["state"] == "simulated"
        assert next(o for o in conversation["outbox"] if o["id"] == "stale-ai")["state"] == "suppressed"
        assert next(o for o in conversation["outbox"] if o["id"] == "legacy-ai")["state"] == "suppressed"
        queue = client.get("/api/dashboard", headers=HEADERS).json()
        assert not next(c for c in queue["customers"] if c["phone"] == phone)["reply_needed"]
        assert (
            next(c for c in queue["customers"] if c["phone"] == phone)["followup_status"] == "awaiting_buyer"
        )
        enqueue(factory, "buyer-replies", phone, "Thank you, can I visit tomorrow?", "simulate")
        queue = client.get("/api/dashboard", headers=HEADERS).json()
        assert next(c for c in queue["customers"] if c["phone"] == phone)["reply_needed"]
        assert next(c for c in queue["customers"] if c["phone"] == phone)["property_id"] == "DEMO-MOHALI-001"


@pytest.mark.asyncio
async def test_reply_guards_and_rechecks_before_delivery(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        phone = test_buyer(client, factory)
        path = f"/api/conversations/{phone}/reply"
        payload = {"text": "Hello", "event_id": "guarded"}
        assert client.post(path, headers=HEADERS, json={**payload, "text": "   "}).status_code == 422
        client.post(f"/api/conversations/{phone}/resume", headers=HEADERS)
        assert client.post(path, headers=HEADERS, json=payload).status_code == 409
        client.post(f"/api/conversations/{phone}/takeover", headers=HEADERS)
        with factory() as session:
            session.get(Customer, phone).last_inbound = now() - 86401
            session.commit()
        assert client.post(path, headers=HEADERS, json=payload).status_code == 409
        enqueue(factory, "renew-window", phone, "Hello again", "simulate")
        assert client.post(path, headers=HEADERS, json=payload).status_code == 202
        enqueue(factory, "buyer-stop", phone, "STOP", "simulate")
        assert (
            client.post(path, headers=HEADERS, json={**payload, "event_id": "after-stop"}).status_code == 409
        )
        await Worker(factory, settings, whatsapp=NoWhatsApp()).send_one()
        with factory() as session:
            assert session.get(Outbox, "human:guarded").state == "suppressed"
        assert not client.get(f"/api/conversations/{phone}", headers=HEADERS).json()["manual_reply_available"]


@pytest.mark.asyncio
async def test_live_human_transport_and_synthetic_session_isolation(factory, settings):
    class FakeWhatsApp:
        def __init__(self):
            self.sent = []

        async def send(self, phone, text):
            self.sent.append((phone, text))
            return "wamid.human-test"

    with TestClient(create_app(settings, factory)) as client:
        phone = test_buyer(client, factory)
        real = "919000000123"
        with factory() as session:
            session.add(Customer(phone=real, paused=True, last_inbound=now()))
            session.commit()
        payload = {"text": "Our team is reviewing your enquiry.", "event_id": "live-reply"}
        assert (
            client.post(f"/api/conversations/{real}/reply", headers=HEADERS, json=payload).status_code == 409
        )
        settings.whatsapp_mode = "live"
        assert (
            client.post(f"/api/conversations/{real}/reply", headers=HEADERS, json=payload).status_code == 202
        )
        transport = FakeWhatsApp()
        worker = Worker(factory, settings, whatsapp=transport)
        await worker.send_one()
        assert transport.sent == [(real, payload["text"])]
        result = client.post(
            f"/api/conversations/{phone}/reply",
            headers=HEADERS,
            json={**payload, "event_id": "synthetic-in-live"},
        )
        assert result.status_code == 202 and result.json()["channel"] == "simulate"
        await worker.send_one()
        assert len(transport.sent) == 1
        with factory() as session:
            assert session.get(Customer, real).paused
            assert session.get(Outbox, "human:live-reply").state == "accepted"
            assert session.get(Outbox, "human:synthetic-in-live").state == "simulated"


@pytest.mark.asyncio
async def test_company_identity_persists_and_is_used_by_agent(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        assert client.put("/api/settings/company", json={"business_name": "Harbor Homes"}).status_code == 401
        assert (
            client.put("/api/settings/company", headers=HEADERS, json={"business_name": "   "}).status_code
            == 422
        )
        phone = test_buyer(client, factory)
        client.post(f"/api/conversations/{phone}/resume", headers=HEADERS)
        client.put("/api/settings/company", headers=HEADERS, json={"business_name": "Harbor Homes"})
        assert client.get("/api/status", headers=HEADERS).json()["business_name"] == "Harbor Homes"
    # A fresh app instance reads the saved value; environment defaults are not mutated.
    assert settings.business_name == "Hukam Realators"
    with TestClient(create_app(settings, factory)) as client:
        assert client.get("/api/status", headers=HEADERS).json()["business_name"] == "Harbor Homes"
        enqueue(factory, "company-hi", phone, "Hi", "simulate")
        with factory() as session:
            reply = await EstateAgent(settings).reply(session, phone, "company-hi")
            assert "AI assistant for Harbor Homes" in reply and "Biba's" not in reply
            session.add(Message(id="reply:company-hi", phone=phone, role="assistant", content=reply))
            session.commit()

        class HandoffModel:
            async def chat(self, messages, tools):
                assert "Harbor Homes" in messages[0]["content"]
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "request_human_handoff",
                                "arguments": {"reason": "Buyer wants team support"},
                            }
                        }
                    ],
                }

        enqueue(factory, "company-help", phone, "Please connect me to your team", "simulate")
        with factory() as session:
            reply = await EstateAgent(settings, HandoffModel()).reply(session, phone, "company-help")
            assert "Harbor Homes team" in reply and "Biba" not in reply
            session.commit()
        assert client.get("/api/dashboard", headers=HEADERS).json()["business_name"] == "Harbor Homes"


def test_overview_exposes_actionable_failures_and_inventory(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        phone = test_buyer(client, factory)
        with factory() as session:
            session.add(
                Outbox(
                    id="uncertain",
                    phone=phone,
                    body="Review",
                    channel="simulate",
                    sender="human",
                    state="delivery_unknown",
                )
            )
            session.add(Job(id="failed", phone=phone, text="Question", channel="simulate", state="failed"))
            session.commit()
        data = client.get("/api/dashboard", headers=HEADERS).json()
        assert data["operations"]["available_properties"] == 1
        assert data["operations"]["demo_properties"] == 1
        assert {i["kind"] for i in data["operations"]["issues"]} == {"delivery_unknown", "agent_failed"}
        assert len(list(factory.database[Outbox.collection].find({"sender": "human"}))) == 1
