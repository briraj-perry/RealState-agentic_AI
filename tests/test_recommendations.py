from estate_ai.db import Customer, Message, Property
from estate_ai.property_templates import seed_demo_inventory
from estate_ai.tools import ToolService


def setup(session):
    session.add(Customer(phone="919876543210"))
    session.add(Customer(phone="919876543211"))
    session.add(Message(id="search-1", phone="919876543210", role="user", content="Show me some homes"))
    session.flush()
    seed_demo_inventory(session)
    return ToolService(session, "919876543210", "search-1", allow_demo=True)


def test_more_properties_returns_new_matches_without_other_buyer_leakage(factory):
    with factory() as session:
        tools = setup(session)
        first = tools.execute("search_properties", {"max_price": 10000000, "limit": 3})["properties"]
        more = tools.execute("search_properties", {"max_price": 10000000, "limit": 5, "exclude_seen": True})[
            "properties"
        ]
        assert len(first) == 3
        assert len(more) == 2
        assert not ({p["id"] for p in first} & {p["id"] for p in more})
        assert all(p["asking_price_inr"] <= 10000000 for p in first + more)
        other = ToolService(session, "919876543211", "other-source", allow_demo=True)
        other_first = other.execute("search_properties", {"max_price": 10000000, "exclude_seen": True})
        assert [p["id"] for p in other_first["properties"]] == [p["id"] for p in first]


def test_no_more_exact_matches_does_not_relax_requirements(factory):
    with factory() as session:
        tools = setup(session)
        filters = {"city": "Mohali", "bedrooms": 3, "max_price": 9000000}
        first = tools.execute("search_properties", filters)["properties"]
        assert len(first) == 1
        assert first[0]["id"] == "DEMO-MOHALI-001"
        assert tools.execute("search_properties", {**filters, "exclude_seen": True}) == {"properties": []}
        session.get(Property, "DEMO-MOHALI-001").available = False
        session.flush()
        assert tools.execute("search_properties", filters) == {"properties": []}


def test_locality_search_is_literal_and_limits_are_validated(factory):
    with factory() as session:
        tools = setup(session)
        result = tools.execute("search_properties", {"city": "Mohali", "locality": "Sector 70"})
        assert [p["id"] for p in result["properties"]] == ["DEMO-MOHALI-001"]
        assert tools.execute("search_properties", {"locality": "%"}) == {"properties": []}
        assert "error" in tools.execute("search_properties", {"limit": 0})
        assert "error" in tools.execute("search_properties", {"limit": 11})
