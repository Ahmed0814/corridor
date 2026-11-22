"""documents models: files attached to shipments (delivery photos, signatures, paperwork)."""

from __future__ import annotations

import uuid

from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class Document(TenantOwnedModel):
    class Kind(models.TextChoices):
        DELIVERY_PHOTO = "delivery_photo"
        DELIVERY_SIGNATURE = "delivery_signature"
        PAPERWORK = "paperwork"

    class Visibility(models.TextChoices):
        INTERNAL = "internal"
        CUSTOMER = "customer"  # shown to the shipment's customer in the portal

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shipment = models.ForeignKey("shipments.Shipment", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    content_type = models.CharField(max_length=64)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=300)  # tenants/<tenant>/documents/<id>
    original_name = models.CharField(max_length=200, blank=True)
    visibility = models.CharField(max_length=16, choices=Visibility.choices, default=Visibility.INTERNAL)
    uploaded_by = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "documents"
        indexes = [models.Index(fields=["tenant", "shipment", "created_at"], name="documents_by_shipment")]
