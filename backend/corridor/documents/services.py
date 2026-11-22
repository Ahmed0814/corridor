"""documents public interface: validated uploads and scoped downloads (D-022, D-070).

Uploads are checked by their bytes, never by the declared type: JPEG, PNG, WebP and PDF only, plus
signatures as JSON stroke data (numbers only, so a signature can never carry a script). Max 10 MB.
Access follows the shipment: anyone who may see the shipment may see its documents, except
customers, who see only documents marked visible to the customer.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from corridor.core.api import ApiError
from corridor.core.lifecycle import not_found
from corridor.core.tenancy import require_tenant_id
from corridor.documents.models import Document
from corridor.documents.schemas import DocumentOut
from corridor.documents.storage import get_storage
from corridor.identity.schemas import RequestContext, Scope

MAX_BYTES = 10 * 1024 * 1024
SIGNATURE_TYPE = "application/vnd.corridor.signature+json"
MAX_SIGNATURE_POINTS = 5000


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def validate_signature(data: bytes) -> dict[str, Any]:
    """{"width": int, "height": int, "strokes": [[[x, y], ...], ...]} with numbers only."""
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ApiError(422, "invalid_signature", "The signature is not valid JSON.") from exc
    if not isinstance(doc, dict) or set(doc) != {"width", "height", "strokes"}:
        raise ApiError(422, "invalid_signature", "The signature must have width, height and strokes only.")
    w, h, strokes = doc["width"], doc["height"], doc["strokes"]
    if not (isinstance(w, int) and isinstance(h, int) and 0 < w <= 4000 and 0 < h <= 4000):
        raise ApiError(422, "invalid_signature", "Invalid signature size.")
    if not isinstance(strokes, list) or not strokes:
        raise ApiError(422, "invalid_signature", "The signature is empty.")
    points = 0
    for stroke in strokes:
        if not isinstance(stroke, list):
            raise ApiError(422, "invalid_signature", "Invalid stroke.")
        for p in stroke:
            ok = (
                isinstance(p, list)
                and len(p) == 2
                and all(isinstance(v, int | float) and not isinstance(v, bool) for v in p)
            )
            if not ok or not (0 <= p[0] <= w and 0 <= p[1] <= h):
                raise ApiError(422, "invalid_signature", "Invalid signature point.")
            points += 1
    if points < 2 or points > MAX_SIGNATURE_POINTS:
        raise ApiError(422, "invalid_signature", "The signature has too few or too many points.")
    return doc


def _out(d: Document) -> DocumentOut:
    return DocumentOut.model_validate(d, from_attributes=True)


def _visible_shipment(ctx: RequestContext, shipment_id: uuid.UUID) -> None:
    from corridor.shipments import services as shipments

    if not shipments.visible(ctx).filter(id=shipment_id).exists():
        raise not_found()


def upload(
    ctx: RequestContext, shipment_id: uuid.UUID, *, kind: str, data: bytes, name: str, visibility: str
) -> DocumentOut:
    _visible_shipment(ctx, shipment_id)
    if ctx.scope == Scope.CUSTOMER:
        raise ApiError(403, "forbidden", "Customers cannot upload documents.")
    if len(data) == 0 or len(data) > MAX_BYTES:
        raise ApiError(422, "invalid_file", "Files must be between 1 byte and 10 MB.")
    if kind == Document.Kind.DELIVERY_SIGNATURE:
        validate_signature(data)
        content_type = SIGNATURE_TYPE
    else:
        sniffed = _sniff(data)
        if sniffed is None:
            raise ApiError(422, "invalid_file", "Only JPEG, PNG, WebP images and PDF documents are accepted.")
        if kind == Document.Kind.DELIVERY_PHOTO and not sniffed.startswith("image/"):
            raise ApiError(422, "invalid_file", "A delivery photo must be an image.")
        content_type = sniffed
    doc_id = uuid.uuid4()
    key = f"tenants/{require_tenant_id()}/documents/{doc_id}"
    get_storage().put(key, data)
    d = Document.for_context(
        id=doc_id,
        shipment_id=shipment_id,
        kind=kind,
        content_type=content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key=key,
        original_name=name[:200],
        visibility=visibility,
        uploaded_by=ctx.user_id,
    )
    d.save()
    return _out(d)


def _get_visible(ctx: RequestContext, document_id: uuid.UUID) -> Document:
    d: Document | None = Document.objects.filter(id=document_id).first()
    if d is None:
        raise not_found()
    _visible_shipment(ctx, d.shipment_id)
    if ctx.scope == Scope.CUSTOMER and d.visibility != Document.Visibility.CUSTOMER:
        raise not_found()
    return d


def list_for_shipment(ctx: RequestContext, shipment_id: uuid.UUID) -> list[DocumentOut]:
    _visible_shipment(ctx, shipment_id)
    qs = Document.objects.filter(shipment_id=shipment_id).order_by("created_at")
    if ctx.scope == Scope.CUSTOMER:
        qs = qs.filter(visibility=Document.Visibility.CUSTOMER)
    return [_out(d) for d in qs]


def content(ctx: RequestContext, document_id: uuid.UUID) -> tuple[Document, bytes]:
    d = _get_visible(ctx, document_id)
    return d, get_storage().get(d.storage_key)


# ---------------------------------------------------------------- used by delivery


def assert_evidence(
    shipment_id: uuid.UUID, *, photo_ids: list[uuid.UUID], signature_id: uuid.UUID | None
) -> None:
    """Delivery evidence must exist, belong to this shipment and be of the right kind."""
    ids = list(photo_ids) + ([signature_id] if signature_id else [])
    rows = {d.id: d for d in Document.objects.filter(id__in=ids, shipment_id=shipment_id)}
    for pid in photo_ids:
        if pid not in rows or rows[pid].kind != Document.Kind.DELIVERY_PHOTO:
            raise ApiError(
                422, "invalid_evidence", "Each photo must be a delivery photo uploaded for this shipment."
            )
    if signature_id is not None and (
        signature_id not in rows or rows[signature_id].kind != Document.Kind.DELIVERY_SIGNATURE
    ):
        raise ApiError(
            422, "invalid_evidence", "The signature must be a signature uploaded for this shipment."
        )


def share_with_customer(document_ids: list[uuid.UUID]) -> None:
    """Delivery evidence becomes visible to the customer once the delivery is confirmed."""
    Document.objects.filter(id__in=document_ids).update(visibility=Document.Visibility.CUSTOMER)
