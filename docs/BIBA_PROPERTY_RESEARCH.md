# Biba property catalog and contextual enquiry testing

## Research and field choices

Housing.com listings expose property identity, location, bedroom/bathroom counts, carpet area,
built-up area, floor, facing, furnishing, parking, balconies and possession. These are more useful
to a first enquiry than a long sales pitch. Some public listings contain conflicting fields; do not
treat a portal description as dealer verification. The example was reviewed for field structure,
not copied into our inventory:
[Housing.com listing example](https://housing.com/in/buy/resale/page/20183547-1-bhk-independent-floor-in-sector-115-for-rs-2490000).

Punjab RERA's project disclosure materials separately identify apartment carpet area, exclusive
balcony/verandah and terrace areas, and project facilities. That supports keeping areas and units
explicit rather than treating every area number as interchangeable:
[Punjab rules](https://rera.punjab.gov.in/pdf/act-rules/Real_Estate_Rules_Punjab.pdf),
[project checklist](https://rera.punjab.gov.in/pdf/checklists/project_registration_other_than_individual.pdf).
This is a product field-design reference, not a legal assessment of any listing.

The resulting catalog records:

- Identity: internal property ID, synthetic Housing reference, fictional project and dealer label.
- Layout: property type, BHK, bathrooms, balconies, carpet/built-up/balcony areas in square feet,
  floor and total floors, facing, room dimensions.
- Interiors: furnishing level, flooring, kitchen, wardrobes, appliances, bathroom fittings and
  removable decorative rug colour/dimensions. A rug is separate from **carpet area**. Staging items
  are explicitly excluded unless the fictional furnishing package includes them.
- Facilities: allocated parking, lift, water arrangements, power backup, security and amenities.
- Transaction: invented asking price, possession, property age, new sale/resale, maintenance and
  exclusions. Final charges, discounts and terms need Biba's approval.
- Unknowns: legal title, RERA registration and nearby-facility distances are unverified. No fake
  registration IDs, guaranteed returns or claimed bank approvals are generated.

The selection of interior fields and conversation design is our implementation choice, not a
claim that every Housing listing supplies them. All 500 records, prices, room sizes and references
are synthetic and are not real Biba stock or market valuations. There are five cities, 1–4 BHK
configurations, four housing types and varied furnishing/possession scenarios. The catalog is
deterministic, so an ID always identifies the same example across restarts. The first eight legacy
IDs remain available. Existing saved inventory is never overwritten by seeding.

## Try it in Estate AI

1. Use simulation mode with `ALLOW_DEMO_DATA=true`. In GitHub, the `production` environment
   variable `ALLOW_DEMO_DATA=true` enables this after a deployment. Live deployments always force
   demo permission off. There is no WhatsApp requirement for app-only testing.
2. Properties → Browse templates. Search location, BHK, property ID, synthetic listing ID or
   descriptive words such as `red`. Expand full specifications.
3. Select **Test this property**, enter Rahul (or another synthetic name), and open the conversation.
   This saves only the selected template if missing. Alternatively explicitly add all sample properties.
4. Send **Hi**. The greeting names the configured company, buyer and property, and labels fiction.
   Ask follow-up questions about the rug, area, fittings, price or visits. Current property facts are
   attached on each turn; they are not inferred from the buyer's short greeting.
5. Say **talk to Biba**. Automation pauses and a handoff summary is saved in Activity & handoffs.
   No external dealer notification or actual calendar booking is sent. Your team can reply from Conversations while AI remains paused.

New conversation also offers a property selector or an existing mapped Housing listing reference.
Sessions retain their own context. Selecting another property creates a new session instead of
silently changing an existing buyer's interest. Asking for a price should receive the asking price
immediately; the assistant should not hide it until the end or negotiate on Biba's behalf.

## Manual listing mapping

The saved Property ID is the canonical inventory identity. A separate `property_listings` document
uses the exact Housing listing reference as its unique key. One listing reference can point to only
one property; multiple references can point to the same property. Conflicting mappings return 409.
In View/edit, enter a Housing.com listing reference and Save. The reference must match the dealer's
actual listing; titles and fuzzy matches are never used to link leads. Fictional references start
`DEMO-` and cannot map to real inventory. The first copied template can be edited but its demo/real
classification cannot be changed.

Authenticated endpoints:

- `PUT /api/housing-listings/{listing_id}` with `{"property_id":"..."}` saves an explicit mapping.
- `GET /api/housing-listings/{listing_id}` resolves it to inventory.
- `POST /api/test-sessions` accepts `buyer_name`, `property_id` and/or `listing_id`.

Unknown references, mismatched IDs and unavailable properties are rejected. This is a manual
mapping and simulated lead flow. Housing.com inbox ingestion, consent handling and proactive
WhatsApp template outreach remain future work. Existing production records are not seeded automatically.
