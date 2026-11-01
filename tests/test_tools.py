from datetime import UTC, datetime, timedelta

from estate_ai.db import Customer, Message, Property, Proposal
from estate_ai.tools import ToolService, confirm_proposal

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
        result = tool.execute(
            "request_site_visit",
            {"property_id": "p1", "start_time": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
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
