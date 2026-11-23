"""Fictional property fixtures for local agent testing; never real market inventory."""

import json

from estate_ai.db import Property, PropertyListing, PropertyMetadata

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


LOCATIONS = [
    ("Mohali", ["Sector 70", "Sector 79", "Sector 115", "Sector 127", "Sector 88"]),
    ("Chandigarh", ["Sector 44", "Sector 35", "Sector 48", "Sector 22", "Sector 63"]),
    ("Panchkula", ["Sector 20", "Sector 12", "Sector 15", "Sector 21", "Sector 25"]),
    ("Zirakpur", ["VIP Road", "Dhakoli", "Patiala Road", "Peer Muchalla", "Gazipur Road"]),
    ("Dera Bassi", ["Barwala Road", "Gulabgarh Road", "Ambala Road", "Saidpura", "Bhankharpur"]),
]


def templates():
    """Stable, reproducible catalog. No scraped listings or real dealer claims."""
    catalog = []
    for index in range(800):
        city, localities = LOCATIONS[index % len(LOCATIONS)]
        bedrooms = 1 + (index // 5) % 4
        kind = ["Apartment", "Builder floor", "Independent house", "Villa"][(index // 20) % 4]
        locality = localities[(index // 100 + index // 25) % len(localities)]
        item = (
            dict(PROPERTY_TEMPLATES[index])
            if index < len(PROPERTY_TEMPLATES)
            else {
                "id": f"DEMO-BIBA-{index + 1:04d}",
                "title": f"DEMO · {bedrooms} BHK {kind.lower()} · {index + 1:04d}",
                "city": city,
                "locality": locality,
                "bedrooms": bedrooms,
                "asking_price": (28 + bedrooms * 16 + (index * 7) % 65) * 100000,
            }
        )
        bedrooms = item["bedrooms"]
        if index < 8:
            kind = (
                "Villa"
                if index == 7
                else "Independent house"
                if index == 3
                else ("Builder floor" if index == 2 else "Apartment")
            )
        carpet = 360 + bedrooms * 245 + (index % 13) * 15
        built_up = carpet + 160 + bedrooms * 35
        floor = index % 8 + 1 if kind == "Apartment" else index % 3
        furnishing = ["Unfurnished", "Semi-furnished", "Fully furnished"][index % 3]
        flooring = [
            "Ivory vitrified tiles",
            "Beige ceramic tiles",
            "Grey porcelain tiles",
            "Wood-look tiles",
        ][index % 4]
        rug = ["Red", "Navy blue", "Beige", "Forest green"][index % 4]
        possession = "Ready to move" if index % 5 else "Under construction; fictional target June 2028"
        details = {
            "dealer": "Biba · synthetic training inventory",
            "housing_listing_id": f"DEMO-HOUSING-BIBA-{index + 1:04d}",
            "project": f"Fictional Biba Gardens {index // 25 + 1:02d}",
            "property_type": kind,
            "carpet_area_sqft": str(carpet),
            "built_up_area_sqft": str(built_up),
            "balcony_area_sqft": str(40 + index % 5 * 12),
            "bedrooms": str(bedrooms),
            "bathrooms": str(max(1, bedrooms - (index % 2))),
            "balconies": str(1 + index % 3),
            "floor": str(floor),
            "total_floors": str(12 if kind == "Apartment" else 3),
            "facing": ["East", "North", "West", "South", "North-East"][index % 5],
            "furnishing": furnishing,
            "living_room": f"{14 + index % 4} × {11 + index % 3} ft; {flooring.lower()}; off-white walls",
            "main_bedroom": f"{12 + index % 4} × {11 + index % 2} ft; space for a double bed",
            "flooring": flooring,
            "kitchen": "Modular L-shaped kitchen; granite counter; stainless-steel sink; exhaust provision",
            "wardrobes": "Not included" if furnishing == "Unfurnished" else "Laminate wardrobes in bedrooms",
            "appliances": "None included"
            if furnishing != "Fully furnished"
            else "2 AC units, refrigerator and geyser",
            "decorative_rug": f"{rug} removable 6 × 4 ft rug; "
            + (
                "included in fictional furnishings"
                if furnishing == "Fully furnished"
                else "staging only, excluded from sale"
            ),
            "bathroom_fittings": "Anti-skid tiles, western WC, shower mixer and geyser provision",
            "parking": f"{1 + index % 2} allocated " + ("covered spaces" if index % 2 else "open spaces"),
            "lift": "Passenger lift" if kind == "Apartment" else "No lift",
            "water": "Municipal supply with overhead tank; daily schedule not verified",
            "power_backup": "Common areas only; apartment inverter provision",
            "security": "Fictional gated entry and common-area CCTV"
            if kind == "Apartment"
            else "Individual entrance",
            "amenities": "Private courtyard and terrace"
            if kind in {"Villa", "Independent house"}
            else [
                "Landscaped courtyard and children's play area",
                "Walking path and community room",
                "Shared garden and bicycle parking",
            ][index % 3],
            "possession": possession,
            "property_age": "New build (fictional)"
            if index % 5 == 0
            else f"{index % 9 + 1} years (fictional)",
            "transaction": "Resale" if index % 2 else "New sale",
            "maintenance": f"Illustrative ₹{1200 + index % 8 * 350}/month; dealer confirmation needed",
            "additional_costs": "Stamp duty, registration, brokerage and taxes excluded; amounts unverified",
            "negotiation": "Asking price is illustrative; Biba must approve any offer or discount",
            "ownership_documents": "Not verified; no legal or ownership claim",
            "rera_registration": "Not verified; no real registration number assigned",
            "nearby_facilities": "Schools, shops and healthcare distances not verified; ask Biba",
            "visit_arrangements": "Request a preferred time; Biba must approve; no booking implied",
            "data_status": "Entirely fictional; not an actual Biba or Housing.com listing",
        }
        description = (
            f"Fictional Biba testing example {index + 1:04d}, not offered for sale. "
            f"{bedrooms} BHK {kind.lower()} in {item['locality']}, {item['city']}. "
            f"Carpet area {carpet} sq ft; built-up area {built_up} sq ft, recorded separately. "
            f"{details['bathrooms']} bathrooms and {details['balconies']} balconies; "
            f"{details['facing']}-facing; {furnishing.lower()}. "
            f"Living room: {details['living_room']}. Main bedroom: {details['main_bedroom']}. "
            f"{details['kitchen']}. Decorative rug: {details['decorative_rug']}. "
            f"Parking: {details['parking']}; lift: {details['lift']}. "
            f"Amenities: {details['amenities']}. Possession: {possession}. "
            "Prices and maintenance are synthetic, not market valuations. "
            "Ownership, RERA status, distances and final charges require dealer verification."
        )
        catalog.append(
            {**item, "available": True, "demo": True, "description": description, "details": details}
        )
    return catalog


def seed_template(session, item):
    if session.get(Property, item["id"]) is not None:
        return False
    session.add(Property(**{key: value for key, value in item.items() if key != "details"}))
    session.add(PropertyMetadata(property_id=item["id"], payload=json.dumps({"details": item["details"]})))
    listing_id = item["details"]["housing_listing_id"]
    mapping = session.get(PropertyListing, listing_id)
    if mapping and mapping.property_id != item["id"]:
        raise ValueError("Synthetic listing reference is already mapped")
    if not mapping:
        session.add(PropertyListing(id=listing_id, property_id=item["id"], demo=True))
    return True


def seed_demo_inventory(session):
    created = []
    for item in templates():
        if seed_template(session, item):
            created.append(item["id"])
    session.flush()
    return created
