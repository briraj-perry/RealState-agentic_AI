"""Review-first inventory import. Workbooks are read as data; formulas never execute."""

import csv
import hashlib
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from pathlib import PurePath
from urllib.parse import unquote
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from defusedxml.common import DefusedXmlException
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import Field, ValidationError
from sqlalchemy import select

from estate_ai.db import Audit, InventoryImport, Property, PropertyMetadata, now
from estate_ai.schemas import PropertyInput, StrictModel

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ROWS, MAX_COLUMNS, MAX_CELLS = 2000, 80, 100_000
FIELDS = {
    "id": ("Property ID", ["id", "propertyid", "listingid", "reference", "ref", "propertycode"]),
    "title": ("Property title", ["title", "propertytitle", "propertyname", "name", "listingtitle"]),
    "city": ("City", ["city", "town"]),
    "locality": ("Locality / sector", ["locality", "location", "sector", "neighbourhood"]),
    "bedrooms": ("Bedrooms / BHK", ["bedrooms", "bedroom", "bhk", "configuration"]),
    "asking_price": (
        "Asking price",
        ["price", "askingprice", "listedprice", "cost", "priceinr", "pricelakh", "priceinlakh", "pricecrore"],
    ),
    "available": ("Availability", ["available", "availability", "status", "listingstatus"]),
    "description": ("Description", ["description", "features", "propertydescription"]),
    "property_type": ("Property type", ["propertytype", "category", "type"]),
    "bathrooms": ("Bathrooms", ["bathrooms", "bathroom", "baths"]),
    "area": ("Area", ["area", "size", "floorarea", "builtuparea", "carpetarea", "areasqft", "areasqyd"]),
    "area_unit": ("Area unit", ["areaunit", "sizeunit", "unit"]),
    "furnishing": ("Furnishing", ["furnishing", "furnished", "furnishingstatus"]),
    "amenities": ("Amenities", ["amenities", "facilities"]),
    "parking": ("Parking", ["parking", "parkingspaces", "carparking"]),
    "floor": ("Floor", ["floor", "floornumber"]),
    "address": ("Address", ["address", "fulladdress"]),
    "possession": ("Possession", ["possession", "possessionstatus", "possessiondate"]),
}
CORE_FIELDS = {"id", "title", "city", "locality", "bedrooms", "asking_price", "available", "description"}


class ImportOptions(StrictModel):
    sheet: str = Field(min_length=1, max_length=100)
    header_row: int = Field(default=1, ge=1, le=20)
    mapping: dict[str, int | None]
    price_unit: str = Field(default="INR", pattern="^(INR|lakh|crore)$")
    update_existing: bool = False
    demo: bool = False
    default_available: bool = False


class CommitOptions(StrictModel):
    skip_invalid: bool = False


def header_key(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("The sheet contains a non-finite number")
    if len(str(value)) > 4000:
        raise ValueError("A cell exceeds the 4,000 character limit")
    return value if isinstance(value, (str, int, float, bool)) else str(value)


def read_sheets(data, filename):
    extension = PurePath(filename).suffix.lower()
    sheets = []
    cells = 0
    if extension == ".xlsx":
        try:
            with ZipFile(BytesIO(data)) as archive:
                if (
                    len(archive.infolist()) > 1000
                    or sum(f.file_size for f in archive.infolist()) > 40 * 1024 * 1024
                ):
                    raise ValueError("Workbook is too large after decompression")
            workbook = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
        except (BadZipFile, KeyError, OSError, ParseError, DefusedXmlException, InvalidFileException) as exc:
            raise ValueError("This is not a readable .xlsx workbook") from exc
        try:
            if len(workbook.worksheets) > 20:
                raise ValueError("A workbook may contain at most 20 worksheets")
            for sheet in workbook.worksheets:
                rows = []
                if sheet.max_column and sheet.max_column > MAX_COLUMNS:
                    raise ValueError(f"Sheet {sheet.title} exceeds {MAX_COLUMNS} columns")
                for index, row in enumerate(sheet.iter_rows(values_only=True), 1):
                    if len(row) > MAX_COLUMNS:
                        raise ValueError(f"Sheet {sheet.title} exceeds {MAX_COLUMNS} columns")
                    if index > MAX_ROWS + 20:
                        raise ValueError(f"Sheet {sheet.title} exceeds the {MAX_ROWS} data-row limit")
                    values = [safe_cell(value) for value in row]
                    cells += len(values)
                    if cells > MAX_CELLS:
                        raise ValueError("Workbook contains too many cells")
                    rows.append(values)
                if any(any(v != "" for v in row) for row in rows):
                    sheets.append({"name": sheet.title, "rows": rows})
        finally:
            workbook.close()
    elif extension == ".csv":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Save the CSV using UTF-8 encoding") from exc
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = []
        for index, row in enumerate(csv.reader(StringIO(text), dialect), 1):
            if index > MAX_ROWS + 20 or len(row) > MAX_COLUMNS:
                raise ValueError(f"CSV exceeds {MAX_ROWS} rows or {MAX_COLUMNS} columns")
            cells += len(row)
            if cells > MAX_CELLS:
                raise ValueError("CSV contains too many cells")
            rows.append([safe_cell(value) for value in row])
        sheets = [{"name": "Inventory", "rows": rows}]
    else:
        raise ValueError("Upload .xlsx or .csv. Save older .xls files as .xlsx first.")
    if not sheets or not any(any(any(v != "" for v in row) for row in sheet["rows"]) for sheet in sheets):
        raise ValueError("The file contains no inventory data")
    return sheets


def suggested_mapping(headers):
    mapping = {}
    for field, (label, aliases) in FIELDS.items():
        found = next(
            (i for i, value in enumerate(headers) if header_key(value) in [*aliases, header_key(label)]), None
        )
        mapping[field] = found
    # Unit suffixes are common in dealer sheets, e.g. Asking Price (Lakh).
    if mapping["asking_price"] is None:
        mapping["asking_price"] = next(
            (
                i
                for i, h in enumerate(headers)
                if "price" in header_key(h)
                and any(unit in header_key(h) for unit in ["lakh", "lac", "crore", "inr"])
            ),
            None,
        )
    return mapping


def sheet_info(sheet):
    rows = sheet["rows"]
    best = max(
        range(min(len(rows), 20)),
        key=lambda i: sum(v is not None for v in suggested_mapping(rows[i]).values()),
    )
    headers = [str(value).strip() or f"Column {i + 1}" for i, value in enumerate(rows[best])]
    mapping = suggested_mapping(headers)
    price_header = header_key(headers[mapping["asking_price"]]) if mapping["asking_price"] is not None else ""
    unit = (
        "lakh"
        if "lakh" in price_header or "lac" in price_header
        else "crore"
        if "crore" in price_header
        else "INR"
    )
    return {
        "name": sheet["name"],
        "header_row": best + 1,
        "headers": headers,
        "suggested_mapping": mapping,
        "price_unit": unit,
        "row_count": max(0, len(rows) - best - 1),
        "header_candidates": [
            {"row": i + 1, "headers": [str(v).strip() or f"Column {j + 1}" for j, v in enumerate(row)]}
            for i, row in enumerate(rows[:20])
        ],
    }


def parse_price(value, unit):
    text = str(value).strip().lower().replace("₹", "").replace(",", "").replace("inr", "").strip()
    text = re.sub(r"^rs\.?\s*", "", text)
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(lakh|lakhs|lac|lacs|l|crore|crores|cr)?", text)
    if not match:
        raise ValueError("Use a numeric asking price, such as 8500000, 85 lakh or 1.2 crore")
    suffix = match[2] or unit.lower()
    factor = (
        100000
        if suffix in {"lakh", "lakhs", "lac", "lacs", "l"}
        else 10000000
        if suffix in {"crore", "crores", "cr"}
        else 1
    )
    amount = Decimal(match[1]) * factor
    if amount != amount.to_integral_value() or amount <= 0 or amount > 2_000_000_000:
        raise ValueError("Asking price must be a positive whole-rupee amount up to INR 2 billion")
    return int(amount)


def integer(value, field):
    text = str(value).strip()
    if field == "bedrooms":
        text = re.sub(r"\s*bhk\s*$", "", text, flags=re.IGNORECASE)
    try:
        number = Decimal(text)
        if not number.is_finite() or number != number.to_integral_value():
            raise ValueError()
        return int(number)
    except (ValueError, InvalidOperation):
        raise ValueError(f"{field} must be a whole number") from None


def availability(value, default):
    if value == "":
        return default
    text = str(value).strip().lower()
    if text in {"true", "yes", "1", "available", "active", "for sale"}:
        return True
    if text in {"false", "no", "0", "unavailable", "sold", "rented", "archived", "on hold"}:
        return False
    raise ValueError("Availability must be Available/Sold, Yes/No, or True/False")


def validate_rows(session, payload, options):
    sheet = next((s for s in payload["sheets"] if s["name"] == options.sheet), None)
    if not sheet or options.header_row > len(sheet["rows"]):
        raise ValueError("Choose a worksheet and a valid header row")
    headers = sheet["rows"][options.header_row - 1]
    mapping = {field: col for field, col in options.mapping.items() if col is not None}
    if any(
        field not in FIELDS or isinstance(col, bool) or col < 0 or col >= len(headers)
        for field, col in mapping.items()
    ):
        raise ValueError("Column mapping contains an invalid field or column")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Each column can be mapped to only one inventory field")
    if not {"city", "bedrooms", "asking_price"}.issubset(mapping):
        raise ValueError("Map City, Bedrooms/BHK and Asking price before validating")
    rows, seen = [], set()
    for row_number, raw in enumerate(sheet["rows"][options.header_row :], options.header_row + 1):
        if not any(value != "" for value in raw):
            continue
        if len(rows) >= MAX_ROWS:
            raise ValueError(f"Import at most {MAX_ROWS} data rows at a time")
        values = {field: raw[col] if col < len(raw) else "" for field, col in mapping.items()}
        errors = []
        normalized = None
        existing = None
        extra = {}
        try:
            if any(isinstance(v, str) and v.lstrip().startswith("=") for v in raw):
                raise ValueError("Replace formulas with their calculated values before importing this row")
            bedrooms = integer(values.get("bedrooms", ""), "bedrooms")
            city = str(values.get("city", "")).strip()
            locality = str(values.get("locality", "")).strip()
            supplied_id = str(values.get("id", "")).strip()
            property_id = (
                supplied_id
                or "XLS-"
                + hashlib.sha256(f"{payload['digest']}:{options.sheet}:{row_number}".encode()).hexdigest()[
                    :16
                ]
            )
            if property_id in seen:
                raise ValueError("Duplicate property ID within this worksheet")
            seen.add(property_id)
            existing = session.get(Property, property_id)
            if existing and "locality" not in mapping:
                locality = existing.locality
            title = str(values.get("title", "")).strip() or (
                existing.title if existing else f"{bedrooms} BHK in {locality or city}"
            )
            core = {
                "id": property_id,
                "title": title,
                "city": city,
                "locality": locality,
                "bedrooms": bedrooms,
                "asking_price": parse_price(values.get("asking_price", ""), options.price_unit),
                "available": availability(
                    values.get("available", ""), existing.available if existing else options.default_available
                ),
                "description": str(values.get("description", "")).strip()
                if "description" in mapping
                else existing.description
                if existing
                else "",
                "demo": options.demo,
            }
            normalized = PropertyInput.model_validate(core).model_dump()
            if existing and not options.update_existing:
                raise ValueError("Property ID already exists. Enable 'Update existing IDs' to update it")
            if existing and existing.demo != options.demo:
                raise ValueError("An existing property's demo/real classification cannot be changed")
            extra = {
                field: str(value).strip()
                for field, value in values.items()
                if field not in CORE_FIELDS and value != ""
            }
            if "bathrooms" in extra:
                extra["bathrooms"] = integer(extra["bathrooms"], "bathrooms")
                if not 0 <= extra["bathrooms"] <= 30:
                    raise ValueError("Bathrooms must be between 0 and 30")
            if "area" in extra:
                number = Decimal(extra["area"].replace(",", ""))
                if not number.is_finite() or number <= 0:
                    raise ValueError("Area must be a positive number")
                extra["area"] = float(number)
                if not math.isfinite(extra["area"]):
                    raise ValueError("Area is too large to import")
                if not extra.get("area_unit"):
                    area_header = header_key(headers[mapping["area"]])
                    if "sqft" in area_header:
                        extra["area_unit"] = "sq ft"
                    elif "sqyd" in area_header:
                        extra["area_unit"] = "sq yd"
                    else:
                        raise ValueError("Map an Area unit column when an area is provided")
        except ValidationError as exc:
            errors = [str(error["loc"][-1]) + ": " + error["msg"] for error in exc.errors()]
        except (ValueError, InvalidOperation) as exc:
            errors = [str(exc) or "Invalid numeric value"]
        source_values = {
            f"{str(headers[i]) if i < len(headers) else 'Column'} [{i + 1}]": value
            for i, value in enumerate(raw)
        }
        rows.append(
            {
                "row_number": row_number,
                "property": normalized,
                "details": extra,
                "source_values": source_values,
                "errors": errors,
                "action": "update" if existing else "create",
                "existing_verified_at": existing.verified_at if existing else None,
            }
        )
    if not rows:
        raise ValueError("No data rows follow the selected header row")
    return rows


def review_data(batch, payload):
    rows = payload.get("validated_rows", [])
    valid = [row for row in rows if not row["errors"]]
    return {
        "id": batch.id,
        "filename": batch.filename,
        "status": batch.status,
        "sheets": [sheet_info(sheet) for sheet in payload["sheets"]],
        "fields": [{"key": field, "label": label} for field, (label, _) in FIELDS.items()],
        "summary": {
            "total": len(rows),
            "valid": len(valid),
            "invalid": len(rows) - len(valid),
            "create": sum(row["action"] == "create" for row in valid),
            "update": sum(row["action"] == "update" for row in valid),
        },
        "rows": [
            {key: value for key, value in row.items() if key not in {"source_values", "existing_verified_at"}}
            for row in rows[:100]
        ],
        "errors": [
            {"row_number": row["row_number"], "errors": row["errors"]} for row in rows if row["errors"]
        ][:100],
        "options": payload.get("options"),
        "result": payload.get("result"),
    }


def register_inventory_import(app, settings, admin):
    router = APIRouter(prefix="/api/inventory-import", dependencies=[Depends(admin)])

    def batch_for(session, import_id):
        batch = session.get(InventoryImport, import_id)
        if not batch:
            raise HTTPException(404, "Import not found")
        if batch.created < now() - 86400 and batch.status != "imported":
            raise HTTPException(410, "Import preview expired. Upload the sheet again")
        return batch

    @router.get("/template.csv")
    def template():
        stream = StringIO()
        csv.writer(stream).writerow([label for label, _ in FIELDS.values()])
        return Response(
            "\ufeff" + stream.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="estate-inventory-template.csv"'},
        )

    @router.post("/preview", status_code=201)
    async def upload(request: Request):
        filename = (
            unquote(request.headers.get("X-Filename", "inventory.xlsx"))
            .replace("\\", "/")
            .split("/")[-1][:200]
        )
        parts, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise HTTPException(413, "Upload a sheet no larger than 8 MB")
            parts.append(chunk)
        data = b"".join(parts)
        try:
            sheets = read_sheets(data, filename)
        except (
            ValueError,
            TypeError,
            OverflowError,
            ParseError,
            DefusedXmlException,
            InvalidFileException,
        ) as exc:
            raise HTTPException(422, str(exc)) from None
        payload = {"sheets": sheets, "digest": hashlib.sha256(data).hexdigest()}
        with request.app.state.factory() as session:
            batch = InventoryImport(filename=filename, payload=json.dumps(payload))
            session.add(batch)
            session.commit()
            return review_data(batch, payload)

    @router.post("/{import_id}/validate")
    def validate(import_id: str, options: ImportOptions, request: Request):
        if options.demo and (not settings.allow_demo_data or settings.whatsapp_mode == "live"):
            raise HTTPException(409, "Demo imports require simulation mode and demo-data permission")
        with request.app.state.factory() as session:
            batch = batch_for(session, import_id)
            if batch.status == "imported":
                raise HTTPException(409, "This import has already been committed")
            payload = json.loads(batch.payload)
            try:
                payload["validated_rows"] = validate_rows(session, payload, options)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            payload["options"] = options.model_dump()
            batch.payload = json.dumps(payload)
            batch.status = "validated"
            session.commit()
            return review_data(batch, payload)

    @router.post("/{import_id}/commit")
    def commit(import_id: str, options: CommitOptions, request: Request):
        with request.app.state.factory() as session:
            batch = session.scalar(
                select(InventoryImport).where(InventoryImport.id == import_id).with_for_update()
            )
            if not batch:
                raise HTTPException(404, "Import not found")
            batch_for(session, import_id)
            payload = json.loads(batch.payload)
            if batch.status == "imported":
                return payload["result"]
            if batch.status != "validated":
                raise HTTPException(409, "Validate and review the sheet before importing")
            import_options = payload["options"]
            if import_options["demo"] and (not settings.allow_demo_data or settings.whatsapp_mode == "live"):
                raise HTTPException(409, "Demo imports are disabled")
            rows = payload["validated_rows"]
            invalid = [row for row in rows if row["errors"]]
            if invalid and not options.skip_invalid:
                raise HTTPException(409, "Fix invalid rows or explicitly choose 'Import valid rows only'")
            valid = [row for row in rows if not row["errors"]]
            if not valid:
                raise HTTPException(409, "There are no valid rows to import")
            created = updated = 0
            for item in valid:
                data = item["property"]
                row = session.scalar(select(Property).where(Property.id == data["id"]).with_for_update())
                if row and (
                    item["existing_verified_at"] is None or row.verified_at != item["existing_verified_at"]
                ):
                    raise HTTPException(
                        409, "Inventory changed after preview. Validate the sheet again before importing"
                    )
                if not row and item["existing_verified_at"] is not None:
                    raise HTTPException(409, "A property changed after preview. Validate the sheet again")
                if row:
                    if row.demo != data["demo"]:
                        raise HTTPException(409, "Demo/real classification changed after preview")
                    for key, value in data.items():
                        setattr(row, key, value)
                    row.verified_at = now()
                    updated += 1
                else:
                    row = Property(**data)
                    session.add(row)
                    session.flush()
                    created += 1
                metadata = session.get(PropertyMetadata, row.id)
                existing_details = json.loads(metadata.payload).get("details", {}) if metadata else {}
                existing_details.update(item["details"])
                meta = {
                    "details": existing_details,
                    "source_values": item["source_values"],
                    "filename": batch.filename,
                    "sheet": import_options["sheet"],
                    "row": item["row_number"],
                }
                if metadata:
                    metadata.payload = json.dumps(meta)
                else:
                    session.add(PropertyMetadata(property_id=row.id, payload=json.dumps(meta)))
            result = {"created": created, "updated": updated, "skipped": len(invalid), "import_id": batch.id}
            payload["result"] = result
            batch.status = "imported"
            batch.payload = json.dumps(payload)
            session.add(Audit(phone="admin", action="inventory_import", detail=json.dumps(result)))
            session.commit()
            return result

    app.include_router(router)
