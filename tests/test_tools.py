import json
from datetime import UTC, datetime, time, timedelta

from fastapi import HTTPException

from estate_ai import apple_calendar, schemas
from estate_ai.agent import EstateAgent
from estate_ai.db import Customer, Message, Property, Proposal, select
from estate_ai.schemas import VISIT_TIME_ZONE, visit_tomorrow
from estate_ai.tools import ToolService, confirm_proposal
from estate_ai.workflows import Worker, enqueue

PHONE = "919876543210"


def setup(session):
    session.add(Customer(phone=PHONE))
    session.add(Message(id="source", phone=PHONE, role="user", content="My offer is 85 lakh"))
    session.add(
        Property(
            id="p1",
            title="Verified apartment",
            city="Mohali",
            bedrooms=3,
            asking_price=8500000,
            available=True,
            demo=False,
        )
    )
    session.flush()
    return ToolService(session, PHONE, "source")


def test_offer_requires_buyer_confirmation_and_cannot_accept_deal(factory):
    with factory() as session:
        tool = setup(session)
        args = {"kind": "offer", "amount_inr": 8500000, "property_id": "p1"}
        result = tool.execute("propose_price_confirmation", args)
        token = result["proposal_id"]
        assert session.get(Proposal, token).status == "pending_confirmation"
        assert tool.execute("propose_price_confirmation", args)["proposal_id"] == token
        assert "couldn't find" in confirm_proposal(session, "911111111111", "CONFIRM " + token, "x")
        reply = confirm_proposal(session, PHONE, "CONFIRM " + token, "buyer-yes")
        assert "not an agreed sale price" in reply
        assert session.get(Proposal, token).status == "buyer_confirmed"
        assert session.get(Proposal, token).confirmation_message_id == "buyer-yes"
        assert "already" in confirm_proposal(session, PHONE, "CONFIRM " + token, "again")


def test_tools_reject_bad_arguments_and_identity_override(factory):
    with factory() as session:
        tool = setup(session)
        assert "error" in tool.execute("execute_sql", {"query": "drop table properties"})
        assert "error" in tool.execute("save_preferences", {"phone": "someone-else"})
        assert "error" in tool.execute("propose_price_confirmation", {"kind": "offer", "amount_inr": -1})
        assert "error" in tool.execute("propose_price_confirmation", {"kind": "offer", "amount_inr": 8500000})
        assert "error" in tool.execute("search_properties", None)


def test_inventory_and_visit_are_grounded(factory):
    with factory() as session:
        tool = setup(session)
        assert tool.execute("search_properties", {"city": "Mohali", "max_price": 8000000}) == {
            "properties": []
        }
        assert (
            tool.execute("search_properties", {"city": "Mohali", "bedrooms": 3})["properties"][0]["id"]
            == "p1"
        )
        assert "error" in tool.execute("get_property_details", {"property_id": "invented"})
        assert "error" in tool.execute(
            "request_site_visit", {"property_id": "p1", "start_time": "2020-01-01T16:00:00+05:30"}
        )
        midnight = datetime.combine(visit_tomorrow(), time(), VISIT_TIME_ZONE)
        for outside_tomorrow in (midnight - timedelta(seconds=1), midnight + timedelta(days=1)):
            result = tool.execute(
                "request_site_visit",
                {
                    "property_id": "p1",
                    "start_time": outside_tomorrow.astimezone(UTC).isoformat(),
                },
            )
            assert "only be requested for tomorrow" in result["error"]
        result = tool.execute(
            "request_site_visit",
            {"property_id": "p1", "start_time": midnight.astimezone(UTC).isoformat()},
        )
        reply = confirm_proposal(session, PHONE, "CONFIRM " + result["proposal_id"], "yes")
        assert "isn't booked" in reply
        assert session.get(Proposal, result["proposal_id"]).status == "requested"


def test_demo_inventory_hidden_and_handoff_blocks_tools(factory):
    with factory() as session:
        tool = setup(session)
        session.get(Property, "p1").demo = True
        session.flush()
        assert tool.execute("search_properties", {}) == {"properties": []}
        assert "error" in tool.execute("get_property_details", {"property_id": "p1"})
        assert tool.execute("request_human_handoff", {"reason": "Buyer needs a human"})["bot_paused"]
        assert "error" in tool.execute("search_properties", {})


def test_yes_confirms_only_the_displayed_proposal(factory):
    with factory() as session:
        tool = setup(session)
        older = tool.execute(
            "propose_price_confirmation", {"kind": "offer", "amount_inr": 7500000, "property_id": "p1"}
        )
        current = tool.execute(
            "propose_price_confirmation", {"kind": "offer", "amount_inr": 8500000, "property_id": "p1"}
        )
        proposal = session.get(Proposal, current["proposal_id"])
        question = tool.confirmation_question(proposal)
        assert "8,500,000" in question and proposal.id not in question
        session.add(Message(id="reply:source", phone=PHONE, role="assistant", content=question))
        session.add(Message(id="answer", phone=PHONE, role="user", content="yes"))
        session.flush()
        reply = ToolService(session, PHONE, "answer").proposal_response("yes")
        assert "awaits the dealer" in reply
        assert proposal.status == "buyer_confirmed"
        assert session.get(Proposal, older["proposal_id"]).status == "pending_confirmation"


async def test_confirmed_visit_syncs_once(factory, settings, monkeypatch):
    with factory() as session:
        setup(session)
        session.commit()

    tomorrow = visit_tomorrow()

    class VisitModel:
        async def chat(self, messages, tools):
            if messages[-1]["role"] == "tool":
                return {"role": "assistant", "content": "Please confirm."}
            assert f"Tomorrow in Asia/Kolkata is {tomorrow}" in messages[0]["content"]
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "request_site_visit",
                            "arguments": {"property_id": "p1", "start_time": f"{tomorrow}T16:00:00+05:30"},
                        }
                    }
                ],
            }

    saved = []
    monkeypatch.setattr(apple_calendar, "available", lambda: True)
    monkeypatch.setattr(apple_calendar, "add_visit", lambda row, title: saved.append(row.id))
    worker = Worker(factory, settings, agent=EstateAgent(settings, model=VisitModel()))
    enqueue(factory, "buyer-visit", PHONE, "Can I visit p1 tomorrow at 4 PM?", "simulate")
    await worker.tick()
    await worker.sync_calendar()
    assert saved == []
    enqueue(factory, "buyer-yes", PHONE, "Yes", "simulate")
    await worker.tick()
    await worker.sync_calendar()
    await worker.sync_calendar()
    with factory() as session:
        row = session.scalar(select(Proposal).where(Proposal.phone == PHONE))
        assert row.status == "requested"
        assert row.confirmation_message_id == "buyer-yes"
        assert row.calendar_state == "saved"
    assert saved == [row.id]


def test_visit_must_still_be_tomorrow_when_buyer_confirms(factory, monkeypatch):
    tomorrow = visit_tomorrow()
    with factory() as session:
        tool = setup(session)
        proposal_id = tool.execute(
            "request_site_visit",
            {
                "property_id": "p1",
                "start_time": f"{tomorrow}T16:00:00+05:30",
            },
        )["proposal_id"]
        monkeypatch.setattr(schemas, "visit_tomorrow", lambda: tomorrow + timedelta(days=1))
        assert "only be requested for tomorrow" in confirm_proposal(
            session, PHONE, "CONFIRM " + proposal_id, "yes"
        )
        row = session.get(Proposal, proposal_id)
        assert row.status == "pending_confirmation"
        assert row.calendar_state == ""


async def test_calendar_recovers_legacy_requests_and_retries_only_eligible_visits(
    factory, settings, monkeypatch
):
    tomorrow = visit_tomorrow()
    with factory() as session:
        setup(session)
        for offset, proposal_id in enumerate(("stale", "pending-buyer", "confirmed")):
            day = tomorrow - timedelta(days=1) if proposal_id == "stale" else tomorrow
            session.add(
                Proposal(
                    id=proposal_id,
                    kind="visit",
                    phone=PHONE,
                    source_message_id="source",
                    created=offset,
                    status="pending_confirmation" if proposal_id == "pending-buyer" else "requested",
                    payload=json.dumps({"property_id": "p1", "start_time": f"{day}T16:00:00+05:30"}),
                )
            )
        session.commit()
    collection = factory.database[Proposal.collection]
    collection.update_many({}, {"$unset": {"calendar_state": "", "calendar_retry_at": ""}})

    attempted = []

    def add_visit(row, title):
        attempted.append((row.id, title))
        if len(attempted) == 1:
            raise HTTPException(503, "Calendar temporarily unavailable")
        return {"status": "added"}

    monkeypatch.setattr(apple_calendar, "available", lambda: True)
    monkeypatch.setattr(apple_calendar, "add_visit", add_visit)
    worker = Worker(factory, settings)
    await worker.sync_calendar()
    await worker.sync_calendar()
    await worker.sync_calendar()
    with factory() as session:
        assert session.get(Proposal, "stale").calendar_state == "needs_new_time"
        assert session.get(Proposal, "pending-buyer").calendar_state == ""
        row = session.get(Proposal, "confirmed")
        assert row.calendar_state == "retrying"
        assert len(attempted) == 1
        row.calendar_retry_at = 0
        session.commit()

    await worker.sync_calendar()
    await worker.sync_calendar()
    with factory() as session:
        assert session.get(Proposal, "confirmed").calendar_state == "saved"
    assert attempted == [("confirmed", "Verified apartment")] * 2
