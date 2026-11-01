"""Fictional property fixtures for local agent testing; never real market inventory."""

from estate_ai.db import Property

PROPERTY_TEMPLATES = [
    {
        "id": "DEMO-MOHALI-001",
        "title": "DEMO · 3 BHK family apartment",
        "city": "Mohali",
        "locality": "Sector 70",
        "bedrooms": 3,
        "asking_price": 8500000,
        "description": "Fictional test apartment with three bedrooms, two bathrooms and one parking space.",
    },
    {
        "id": "DEMO-MOHALI-002",
        "title": "DEMO · 2 BHK starter apartment",
        "city": "Mohali",
        "locality": "Sector 127",
        "bedrooms": 2,
        "asking_price": 6200000,
        "description": "Fictional test apartment with two bedrooms, a balcony and lift access.",
    },
    {
        "id": "DEMO-MOHALI-003",
        "title": "DEMO · 3 BHK builder floor",
        "city": "Mohali",
        "locality": "Sector 79",
        "bedrooms": 3,
        "asking_price": 9800000,
        "description": "Fictional test builder floor with three bedrooms, a study nook and covered parking.",
    },
    {
        "id": "DEMO-CHANDIGARH-001",
        "title": "DEMO · 4 BHK independent home",
        "city": "Chandigarh",
        "locality": "Sector 44",
        "bedrooms": 4,
        "asking_price": 18500000,
        "description": "Fictional test independent home with four bedrooms and a small private garden.",
    },
    {
        "id": "DEMO-PANCHKULA-001",
        "title": "DEMO · 3 BHK spacious apartment",
        "city": "Panchkula",
        "locality": "Sector 20",
        "bedrooms": 3,
        "asking_price": 12000000,
        "description": "Fictional test apartment with three bedrooms, three bathrooms and a balcony.",
    },
    {
        "id": "DEMO-ZIRAKPUR-001",
        "title": "DEMO · 1 BHK compact apartment",
        "city": "Zirakpur",
        "locality": "VIP Road",
        "bedrooms": 1,
        "asking_price": 3200000,
        "description": "Fictional test apartment with one bedroom, one bathroom and an open kitchen.",
    },
    {
        "id": "DEMO-ZIRAKPUR-002",
        "title": "DEMO · 2 BHK family apartment",
        "city": "Zirakpur",
        "locality": "Dhakoli",
        "bedrooms": 2,
        "asking_price": 5800000,
        "description": "Fictional test apartment with two bedrooms, two bathrooms and one parking space.",
    },
    {
        "id": "DEMO-DERABASSI-001",
        "title": "DEMO · 4 BHK villa",
        "city": "Dera Bassi",
        "locality": "Barwala Road",
        "bedrooms": 4,
        "asking_price": 11200000,
        "description": "Fictional test villa with four bedrooms, a terrace and a private courtyard.",
    },
]


def templates():
    return [
        {
            **item,
            "available": True,
            "demo": True,
            "description": item["description"] + " Demonstration only; not offered for sale.",
        }
        for item in PROPERTY_TEMPLATES
    ]


def seed_demo_inventory(session):
    created = []
    for item in templates():
        if session.get(Property, item["id"]) is None:
            session.add(Property(**item))
            created.append(item["id"])
    session.flush()
    return created
