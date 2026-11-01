import csv
from io import BytesIO, StringIO
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.testclient import TestClient
from PIL import Image

from estate_ai.db import InventoryImport, Property, PropertyMetadata, now
from estate_ai.main import create_app
from estate_ai.tools import property_data

HEADERS = {"X-API-Key": "test-admin-secret"}


def csv_bytes(rows):
    stream = StringIO()
    csv.writer(stream).writerows(rows)
    return stream.getvalue().encode("utf-8")


def xlsx_bytes(sheets):
    """Minimal OOXML fixture, with real numeric and formula cells; no spreadsheet writer dependency."""
    stream = BytesIO()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + overrides
            + "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        sheet_tags = "".join(
            f'<sheet name={quoteattr(name)} sheetId="{i}" r:id="rId{i}"/>'
            for i, (name, _) in enumerate(sheets, 1)
        )
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{sheet_tags}</sheets></workbook>',
        )
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + rels
            + "</Relationships>",
        )
        for sheet_index, (_, rows) in enumerate(sheets, 1):
            xml_rows = []
            for row_index, row in enumerate(rows, 1):
                cells = []
                for col_index, value in enumerate(row, 1):
                    column = ""
                    index = col_index
                    while index:
                        index, rem = divmod(index - 1, 26)
                        column = chr(65 + rem) + column
                    ref = column + str(row_index)
                    if isinstance(value, (int, float)):
                        cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                    elif str(value).startswith("="):
                        cells.append(f'<c r="{ref}"><f>{escape(str(value)[1:])}</f><v>85</v></c>')
                    else:
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
                xml_rows.append(f'<row r="{row_index}">' + "".join(cells) + "</row>")
            archive.writestr(
                f"xl/worksheets/sheet{sheet_index}.xml",
                f'<worksheet xmlns="{ns}"><sheetData>' + "".join(xml_rows) + "</sheetData></worksheet>",
            )
    return stream.getvalue()


def upload(client, data, filename="inventory.csv"):
    result = client.post(
        "/api/inventory-import/preview", content=data, headers={**HEADERS, "X-Filename": filename}
    )
    assert result.status_code == 201, result.text
    return result.json()


def validate(client, batch, **overrides):
    sheet = batch["sheets"][0]
    options = {
        "sheet": sheet["name"],
        "header_row": sheet["header_row"],
        "mapping": sheet["suggested_mapping"],
        "price_unit": sheet["price_unit"],
        "default_available": True,
        **overrides,
    }
    result = client.post(f"/api/inventory-import/{batch['id']}/validate", headers=HEADERS, json=options)
    assert result.status_code == 200, result.text
    return result.json()


def commit(client, batch_id, **options):
    return client.post(f"/api/inventory-import/{batch_id}/commit", headers=HEADERS, json=options)


def test_xlsx_multi_sheet_prices_details_and_private_source(factory, settings):
    rows = [
        ["BIBA inventory"],
        [
            "Property ID",
            "Title",
            "City",
            "Sector",
            "BHK",
            "Price (Lakh)",
            "Bathrooms",
            "Area (sqft)",
            "Furnishing",
            "Owner phone",
            "Owner notes",
            "Status",
        ],
        [
            "BIBA-01",
            "Family apartment",
            "Mohali",
            "Sector 70",
            "3 BHK",
            85,
            2,
            1450,
            "Semi-furnished",
            "FAKE-OWNER-CONTACT",
            "Internal callback note",
            "Available",
        ],
        [
            "BIBA-02",
            "Large apartment",
            "Panchkula",
            "Sector 20",
            3,
            "1.2 crore",
            3,
            1800,
            "Unfurnished",
            "FAKE-OTHER-CONTACT",
            "Internal only",
            "Sold",
        ],
    ]
    data = xlsx_bytes(
        [("Current inventory", rows), ("Archive", [["City", "BHK", "Price"], ["Mohali", 2, 6000000]])]
    )
    with TestClient(create_app(settings, factory)) as client:
        batch = upload(client, data, "biba.xlsx")
        assert len(batch["sheets"]) == 2
        assert batch["sheets"][0]["header_row"] == 2
        preview = validate(client, batch)
        assert preview["summary"] == {"total": 2, "valid": 2, "invalid": 0, "create": 2, "update": 0}
        assert preview["rows"][0]["property"]["asking_price"] == 8500000
        assert preview["rows"][1]["property"]["asking_price"] == 12000000
        assert not preview["rows"][1]["property"]["available"]
        assert client.get("/api/properties", headers=HEADERS).json() == []
        assert commit(client, batch["id"]).json()["created"] == 2
        assert commit(client, batch["id"]).json()["created"] == 2
        properties = client.get("/api/properties", headers=HEADERS).json()
        assert len(properties) == 2
        row = next(p for p in properties if p["id"] == "BIBA-01")
        assert row["details"]["area"] == 1450
        assert row["details"]["area_unit"] == "sq ft"
        assert row["details"]["bathrooms"] == 2
        assert "FAKE-OWNER-CONTACT" in str(row["import_source"])
        with factory() as session:
            public = property_data(session.get(Property, "BIBA-01"))
            assert "FAKE-OWNER-CONTACT" not in str(public)
            assert "Internal callback note" not in str(public)
            assert "import_source" not in public


def test_csv_validation_duplicate_ids_and_explicit_partial_import(factory, settings):
    data = csv_bytes(
        [
            ["Property ID", "City", "BHK", "Price", "Status"],
            ["p1", "Mohali", 3, "₹85,00,000", "Available"],
            ["p1", "Mohali", 2, 6200000, "Available"],
            ["p2", "", 3, "not a price", "Available"],
            ["p3", "Zirakpur", 2, "58 lakh", "Available"],
        ]
    )
    with TestClient(create_app(settings, factory)) as client:
        batch = upload(client, data)
        preview = validate(client, batch)
        assert preview["summary"]["valid"] == 2
        assert preview["summary"]["invalid"] == 2
        assert commit(client, batch["id"]).status_code == 409
        result = commit(client, batch["id"], skip_invalid=True).json()
        assert result["created"] == 2 and result["skipped"] == 2


def test_updates_require_permission_and_preserve_unmapped_details(factory, settings):
    with factory() as session:
        session.add(
            Property(
                id="p1",
                title="Original title",
                city="Mohali",
                locality="Sector 70",
                bedrooms=3,
                asking_price=8500000,
                available=False,
                description="Original description",
            )
        )
        session.add(PropertyMetadata(property_id="p1", payload='{"details":{"furnishing":"Furnished"}}'))
        session.commit()
    data = csv_bytes([["Property ID", "City", "BHK", "Price"], ["p1", "Mohali", 3, 8700000]])
    with TestClient(create_app(settings, factory)) as client:
        photo_bytes = BytesIO()
        Image.new("RGB", (20, 20), "green").save(photo_bytes, format="PNG")
        photo = client.post(
            "/api/properties/p1/photos", headers=HEADERS, content=photo_bytes.getvalue()
        ).json()
        batch = upload(client, data)
        assert validate(client, batch)["summary"]["invalid"] == 1
        preview = validate(client, batch, update_existing=True)
        assert preview["summary"]["update"] == 1
        assert preview["rows"][0]["property"]["title"] == "Original title"
        assert not preview["rows"][0]["property"]["available"]
        assert commit(client, batch["id"]).json()["updated"] == 1
        row = client.get("/api/properties", headers=HEADERS).json()[0]
        assert row["description"] == "Original description" and row["locality"] == "Sector 70"
        assert row["details"]["furnishing"] == "Furnished"
        assert row["photos"][0]["id"] == photo["id"]


def test_stale_preview_rolls_back_entire_import(factory, settings):
    with factory() as session:
        for index in [1, 2]:
            session.add(
                Property(id=f"p{index}", title="Original", city="Mohali", bedrooms=3, asking_price=8500000)
            )
        session.commit()
    with TestClient(create_app(settings, factory)) as client:
        batch = upload(
            client,
            csv_bytes(
                [
                    ["Property ID", "City", "BHK", "Price"],
                    ["p1", "Mohali", 3, 8600000],
                    ["p2", "Mohali", 3, 8700000],
                ]
            ),
        )
        validate(client, batch, update_existing=True)
        with factory() as session:
            session.get(Property, "p2").verified_at = now() + 1
            session.commit()
        assert commit(client, batch["id"]).status_code == 409
        with factory() as session:
            assert session.get(Property, "p1").asking_price == 8500000
            assert session.get(InventoryImport, batch["id"]).status == "validated"


def test_formulas_are_rejected_and_generated_ids_are_stable(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        batch = upload(
            client,
            xlsx_bytes([("Inventory", [["City", "BHK", "Price"], ["Mohali", 3, "=40+45"]])]),
            "formula.xlsx",
        )
        preview = validate(client, batch)
        assert "formulas" in preview["rows"][0]["errors"][0]
        assert commit(client, batch["id"]).status_code == 409
        data = csv_bytes([["City", "BHK", "Price"], ["Mohali", 3, "85 lakh"]])
        first = validate(client, upload(client, data))
        second = validate(client, upload(client, data))
        assert first["rows"][0]["property"]["id"] == second["rows"][0]["property"]["id"]


def test_auth_bad_formats_and_mapping_errors(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        assert client.post("/api/inventory-import/preview", content=b"hello").status_code == 401
        assert (
            client.post(
                "/api/inventory-import/preview",
                headers={**HEADERS, "X-Filename": "old.xls"},
                content=b"hello",
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/inventory-import/preview",
                headers={**HEADERS, "X-Filename": "bad.xlsx"},
                content=b"hello",
            ).status_code
            == 422
        )
        batch = upload(client, csv_bytes([["City", "BHK", "Price"], ["Mohali", 3, 8500000]]))
        assert commit(client, batch["id"]).status_code == 409
        assert (
            client.post(
                f"/api/inventory-import/{batch['id']}/validate",
                headers=HEADERS,
                json={"sheet": "Inventory", "mapping": {"city": 0, "bedrooms": 0, "asking_price": 2}},
            ).status_code
            == 422
        )
        template = client.get("/api/inventory-import/template.csv", headers=HEADERS)
        assert template.status_code == 200
        template_batch = upload(client, template.content)
        mapping = template_batch["sheets"][0]["suggested_mapping"]
        assert all(mapping[field] is not None for field in ["city", "bedrooms", "asking_price", "locality"])
