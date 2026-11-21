"""customers models. Private to this module (DECISIONS D-005)."""

from __future__ import annotations

import uuid

from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class Customer(TenantOwnedModel):
    class Status(models.TextChoices):
        ACTIVE = "active"
        INACTIVE = "inactive"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    tax_id = models.CharField(max_length=64, blank=True)
    email = models.EmailField(blank=True)
    phone_e164 = models.CharField(max_length=16, blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "customers"
        indexes = [models.Index(fields=["tenant", "name"], name="customers_tenant_name_idx")]


class CustomerContact(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=200)
    role = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone_e164 = models.CharField(max_length=16, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customer_contacts"
