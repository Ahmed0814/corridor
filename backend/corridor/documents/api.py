"""documents Ninja router: upload to a shipment, list, download."""

from __future__ import annotations

import uuid
from typing import Literal

from django.http import HttpRequest, HttpResponse
from ninja import File, Form, Router, Status
from ninja.files import UploadedFile

from corridor.core.idempotency import idempotent
from corridor.documents import services
from corridor.documents.schemas import DocumentOut
from corridor.identity.services import ctx_of, requires, tenant_auth

router = Router(tags=["documents"], auth=tenant_auth)


@router.post(
    "/shipments/{shipment_id}/documents",
    response={201: DocumentOut},
    summary="Upload a delivery photo, signature or paperwork (≤ 10 MB, checked by content)",
)
@requires("documents.upload")
@idempotent
def upload(
    request: HttpRequest,
    shipment_id: uuid.UUID,
    file: File[UploadedFile],
    kind: Form[Literal["delivery_photo", "delivery_signature", "paperwork"]],
    visibility: Form[Literal["internal", "customer"]] = "internal",
) -> Status[DocumentOut]:
    data = file.read(services.MAX_BYTES + 1)
    return Status(
        201,
        services.upload(
            ctx_of(request), shipment_id, kind=kind, data=data, name=file.name or "", visibility=visibility
        ),
    )


@router.get(
    "/shipments/{shipment_id}/documents", response=list[DocumentOut], summary="Documents of a shipment"
)
@requires("documents.read")
def list_documents(request: HttpRequest, shipment_id: uuid.UUID) -> list[DocumentOut]:
    return services.list_for_shipment(ctx_of(request), shipment_id)


@router.get("/documents/{document_id}/content", summary="Download a document")
@requires("documents.read")
def download(request: HttpRequest, document_id: uuid.UUID) -> HttpResponse:
    doc, data = services.content(ctx_of(request), document_id)
    response = HttpResponse(data, content_type=doc.content_type)
    disposition = "inline" if doc.content_type.startswith("image/") else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{doc.id}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
    return response
