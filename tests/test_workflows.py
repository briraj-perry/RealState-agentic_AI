import pytest
from sqlalchemy import select

from estate_ai.agent import EstateAgent
from estate_ai.db import Customer, Job, Message, Outbox, Property, now
from estate_ai.workflows import Worker, enqueue

PHONE = "919876543210"


class FakeModel:
    def __init__(self):
        self.calls = 0

    async def chat(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "search_properties", "arguments": {"city": "Mohali"}}}],
            }
        assert any(m["role"] == "tool" and "8500000" in m["content"] for m in messages)
        return {"role": "assistant", "content": "I'm the AI assistant. This apartment is listed at ₹85 lakh."}


class FakeWhatsApp:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send(self, phone, body):
        self.sent.append((phone, body))
        if self.fail:
            raise TimeoutError("Ambiguous delivery")
        return "wamid.outbound"


@pytest.mark.asyncio
async def test_agent_graph_to_simulated_outbox(factory, settings):
    with factory() as session:
        session.add(Property(id="p1", title="Apartment", city="Mohali", bedrooms=3, asking_price=8500000))
        session.commit()
    assert enqueue(factory, "msg1", PHONE, "Show Mohali homes", "simulate")
    assert not enqueue(factory, "msg1", PHONE, "Show Mohali homes", "simulate")
    model = FakeModel()
    worker = Worker(factory, settings, agent=EstateAgent(settings, model))
    await worker.tick()
    with factory() as session:
        assert session.get(Job, "msg1").state == "done"
        assert session.get(Outbox, "msg1").state == "simulated"
        assert "85 lakh" in session.get(Message, "reply:msg1").content
    assert model.calls == 2


@pytest.mark.asyncio
async def test_stop_blocks_queued_work_and_delivery(factory, settings):
    enqueue(factory, "msg1", PHONE, "Hello", "simulate")
    enqueue(factory, "stop", PHONE, "STOP", "simulate")
    worker = Worker(factory, settings)
    await worker.tick()
    with factory() as session:
        assert session.get(Customer, PHONE).opted_out
        assert session.get(Job, "msg1").state == "suppressed"
        assert not list(session.scalars(select(Outbox)))


@pytest.mark.asyncio
async def test_expired_window_suppresses_send(factory, settings):
    with factory() as session:
        session.add(Customer(phone=PHONE, last_inbound=now() - 90000))
        session.add(Outbox(id="out", phone=PHONE, body="Hello", channel="whatsapp"))
        session.commit()
    whatsapp = FakeWhatsApp()
    await Worker(factory, settings, whatsapp=whatsapp).send_one()
    assert not whatsapp.sent
    with factory() as session:
        assert session.get(Outbox, "out").state == "suppressed"


@pytest.mark.asyncio
async def test_ambiguous_send_is_not_automatically_retried(factory, settings):
    settings.whatsapp_mode = "live"  # Transport mocked; no real credentials or sends.
    with factory() as session:
        session.add(Customer(phone=PHONE, last_inbound=now()))
        session.add(Outbox(id="out", phone=PHONE, body="Hello", channel="whatsapp"))
        session.commit()
    whatsapp = FakeWhatsApp(fail=True)
    worker = Worker(factory, settings, whatsapp=whatsapp)
    await worker.send_one()
    await worker.send_one()
    assert len(whatsapp.sent) == 1
    with factory() as session:
        assert session.get(Outbox, "out").state == "delivery_unknown"


@pytest.mark.asyncio
async def test_takeover_during_model_call_suppresses_reply(factory, settings):
    class TakeoverAgent:
        async def reply(self, session, phone, message_id):
            with factory() as other:
                other.get(Customer, phone).paused = True
                other.commit()
            return "Should not send"

    enqueue(factory, "msg1", PHONE, "Hello", "simulate")
    await Worker(factory, settings, agent=TakeoverAgent()).tick()
    with factory() as session:
        assert session.get(Job, "msg1").state == "suppressed"
        assert session.get(Outbox, "msg1") is None


@pytest.mark.asyncio
async def test_repeated_failure_pauses_and_recovery_does_not_resend(factory, settings):
    class FailingAgent:
        async def reply(self, session, phone, message_id):
            raise TimeoutError("Provider failure")

    enqueue(factory, "failure", PHONE, "Hi", "simulate")
    worker = Worker(factory, settings, agent=FailingAgent())
    for _ in range(3):
        with factory() as session:
            session.get(Job, "failure").next_attempt = 0
            session.commit()
        await worker.tick()
    with factory() as session:
        assert session.get(Job, "failure").state == "failed"
        assert session.get(Customer, PHONE).paused
        session.add(Outbox(id="interrupted", phone=PHONE, body="hello", channel="whatsapp", state="sending"))
        session.commit()
    worker.recover()
    with factory() as session:
        assert session.get(Outbox, "interrupted").state == "delivery_unknown"
