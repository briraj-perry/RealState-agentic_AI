import asyncio
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from estate_ai.db import Customer, Message
from estate_ai.main import create_app
from estate_ai.tools import ToolService

HEADERS = {"X-API-Key": "test-admin-secret"}


def image_bytes(width=30, height=20):
    output = BytesIO()
    image = Image.new("RGB", (width, height), "#48724d")
    exif = Image.Exif()
    exif[270] = "Synthetic private test metadata"
    image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


def listing(client, property_id="p1"):
    response = client.put(
        "/api/properties/" + property_id,
        headers=HEADERS,
        json={
            "id": property_id,
            "title": "Test apartment",
            "city": "Mohali",
            "bedrooms": 3,
            "asking_price": 8500000,
        },
    )
    assert response.status_code == 200


def test_photos_upload_persist_privately_resize_and_strip_metadata(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        listing(client)
        data = image_bytes(2000, 1000)
        assert client.post("/api/properties/p1/photos", content=data).status_code == 401
        response = client.post("/api/properties/p1/photos", headers=HEADERS, content=data)
        assert response.status_code == 201
        photo = response.json()
        assert client.get(photo["url"]).status_code == 401
        saved = client.get(photo["url"], headers=HEADERS)
        assert saved.headers["content-type"] == "image/jpeg"
        assert saved.headers["cache-control"] == "private, no-store"
        with Image.open(BytesIO(saved.content)) as image:
            assert image.size == (1800, 900)
            assert not image.getexif()
        repeated = client.post("/api/properties/p1/photos", headers=HEADERS, content=data).json()
        assert repeated["id"] == photo["id"]
        assert client.get("/api/properties", headers=HEADERS).json()[0]["photos"] == [photo]
    with TestClient(create_app(settings, factory)) as client:
        assert client.get(photo["url"], headers=HEADERS).status_code == 200


def test_invalid_and_oversized_uploads_and_wrong_property_removal(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        listing(client)
        assert (
            client.post("/api/properties/missing/photos", headers=HEADERS, content=image_bytes()).status_code
            == 404
        )
        assert (
            client.post(
                "/api/properties/p1/photos", headers=HEADERS, content=b'<svg onload="alert(1)"></svg>'
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/properties/p1/photos", headers=HEADERS, content=b"x" * (8 * 1024 * 1024 + 1)
            ).status_code
            == 413
        )
        photo = client.post("/api/properties/p1/photos", headers=HEADERS, content=image_bytes()).json()
        assert (
            client.delete("/api/properties/other/photos/" + photo["id"], headers=HEADERS).status_code == 404
        )
        assert client.delete("/api/properties/p1/photos/" + photo["id"], headers=HEADERS).status_code == 204
        assert client.get(photo["url"], headers=HEADERS).status_code == 404


def test_photo_limit_and_demo_protection(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        listing(client)
        for i in range(10):
            assert (
                client.post(
                    "/api/properties/p1/photos", headers=HEADERS, content=image_bytes(20 + i)
                ).status_code
                == 201
            )
        assert (
            client.post("/api/properties/p1/photos", headers=HEADERS, content=image_bytes(50)).status_code
            == 409
        )
        client.post("/api/demo/seed", headers=HEADERS)
    settings.allow_demo_data = False
    with TestClient(create_app(settings, factory)) as client:
        assert (
            client.post(
                "/api/properties/DEMO-MOHALI-001/photos", headers=HEADERS, content=image_bytes()
            ).status_code
            == 409
        )


def test_browse_and_more_cards_are_bound_to_real_tool_results_and_photos(factory, settings):
    class NoModel:
        async def reply(self, *args):
            raise AssertionError("Inventory buttons must call the tools reliably without depending on prose")

    with TestClient(create_app(settings, factory, agent=NoModel())) as client:
        client.post("/api/demo/seed", headers=HEADERS)
        photo = client.post(
            "/api/properties/DEMO-ZIRAKPUR-001/photos", headers=HEADERS, content=image_bytes()
        ).json()
        phone = client.post("/api/test-sessions", headers=HEADERS, json={"name": "Cards test"}).json()[
            "phone"
        ]
        queued = client.post(f"/api/test-sessions/{phone}/browse-properties", headers=HEADERS)
        assert queued.status_code == 202
        assert client.post(f"/api/test-sessions/{phone}/more-properties", headers=HEADERS).status_code == 409
        asyncio.run(client.app.state.worker.tick())
        first = client.get(f"/api/conversations/{phone}/recommendations", headers=HEADERS).json()
        assert first["has_search"] and first["has_more"]
        first_ids = {p["id"] for p in first["batches"][0]["properties"]}
        assert len(first_ids) == 3
        assert first["batches"][0]["properties"][0]["photos"][0]["id"] == photo["id"]
        assert client.post(f"/api/test-sessions/{phone}/more-properties", headers=HEADERS).status_code == 202
        asyncio.run(client.app.state.worker.tick())
        more = client.get(f"/api/conversations/{phone}/recommendations", headers=HEADERS).json()
        more_ids = {p["id"] for p in more["batches"][-1]["properties"]}
        assert len(more_ids) == 5
        assert not (first_ids & more_ids)
        assert not more["has_more"]
        conversation = client.get(f"/api/conversations/{phone}", headers=HEADERS).json()
        assert any(
            m["id"] == "reply:" + more["batches"][-1]["source_message_id"] for m in conversation["messages"]
        )


def test_more_button_preserves_budget_and_does_not_contact_real_buyers(factory, settings):
    with TestClient(create_app(settings, factory)) as client:
        client.post("/api/demo/seed", headers=HEADERS)
        phone = client.post("/api/test-sessions", headers=HEADERS, json={}).json()["phone"]
        with factory() as session:
            session.add(Message(id="filters", phone=phone, role="user", content="3 BHK Mohali under 90 lakh"))
            session.flush()
            ToolService(session, phone, "filters", True).execute(
                "search_properties", {"city": "Mohali", "bedrooms": 3, "max_price": 9000000}
            )
            session.add(Customer(phone="919000000001"))
            session.commit()
        assert (
            client.post("/api/test-sessions/919000000001/more-properties", headers=HEADERS).status_code == 404
        )
        assert client.post(f"/api/test-sessions/{phone}/more-properties", headers=HEADERS).status_code == 202
        asyncio.run(client.app.state.worker.tick())
        result = client.get(f"/api/conversations/{phone}/recommendations", headers=HEADERS).json()
        assert not result["has_more"]
        assert result["batches"][-1]["properties"] == []
        assert result["batches"][-1]["filters"]["max_price"] == 9000000
