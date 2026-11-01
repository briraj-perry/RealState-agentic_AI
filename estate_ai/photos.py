"""Validated, private property photos stored in the existing SQL database."""

import hashlib
import warnings
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select

from estate_ai.db import Property, PropertyPhoto

MAX_BYTES = 8 * 1024 * 1024
MAX_PHOTOS = 10


def photo_data(photo):
    return {"id": photo.id, "url": "/api/property-photos/" + photo.id, "created": photo.created}


def normalize_image(data: bytes) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Use a JPEG, PNG or WebP photo")
                if image.width * image.height > 20_000_000:
                    raise ValueError("Photo dimensions are too large (maximum 20 megapixels)")
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((1800, 1800))
                output = BytesIO()
                image.save(output, format="JPEG", quality=85)
                return output.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("Upload a valid JPEG, PNG or WebP photo") from exc


def register_photos(app, settings, admin):
    router = APIRouter(prefix="/api", dependencies=[Depends(admin)])

    @router.post("/properties/{property_id}/photos", status_code=201)
    async def upload(property_id: str, request: Request):
        with request.app.state.factory() as session:
            row = session.get(Property, property_id)
            if not row:
                raise HTTPException(404, "Property not found")
            if row.demo and (not settings.allow_demo_data or settings.whatsapp_mode == "live"):
                raise HTTPException(409, "Demo photos require simulation mode and demo-data permission")
        parts, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BYTES:
                raise HTTPException(413, "Each photo must be no larger than 8 MB")
            parts.append(chunk)
        try:
            data = normalize_image(b"".join(parts))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        digest = hashlib.sha256(data).hexdigest()
        with request.app.state.factory() as session:
            session.scalar(select(Property).where(Property.id == property_id).with_for_update())
            existing = session.scalar(
                select(PropertyPhoto).where(
                    PropertyPhoto.property_id == property_id, PropertyPhoto.digest == digest
                )
            )
            if existing:
                return photo_data(existing)
            count = session.scalar(
                select(func.count())
                .select_from(PropertyPhoto)
                .where(PropertyPhoto.property_id == property_id)
            )
            if count >= MAX_PHOTOS:
                raise HTTPException(409, "A property can have at most 10 photos")
            photo = PropertyPhoto(property_id=property_id, data=data, digest=digest)
            session.add(photo)
            session.commit()
            return photo_data(photo)

    @router.get("/property-photos/{photo_id}")
    def read(photo_id: str, request: Request):
        with request.app.state.factory() as session:
            photo = session.get(PropertyPhoto, photo_id)
            if not photo:
                raise HTTPException(404, "Photo not found")
            return Response(
                photo.data,
                media_type="image/jpeg",
                headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
            )

    @router.delete("/properties/{property_id}/photos/{photo_id}", status_code=204)
    def remove(property_id: str, photo_id: str, request: Request):
        with request.app.state.factory() as session:
            photo = session.get(PropertyPhoto, photo_id)
            if not photo or photo.property_id != property_id:
                raise HTTPException(404, "Photo not found for this property")
            session.delete(photo)
            session.commit()
        return Response(status_code=204)

    app.include_router(router)
