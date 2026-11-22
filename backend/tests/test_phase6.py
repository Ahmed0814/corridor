"""Phase 6: geofences/checkpoints, deterministic ETA, public tracking links, notifications,
proof of delivery (photo + signature) and the customer view of documents.

MASTER_PROMPT Phase 6 DoD: tracking links revocable/expiring/allowlisted; checkpoints and geofences
trigger events; border GPS arrival is never clearance (hard rule 8); an older point never moves ETA;
notifications are idempotent and never send real email without approval.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from django.contrib.gis.geos import Point
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from corridor.core import ratelimit
from corridor.core.api import ApiError
from corridor.core.tenancy import tenant_context
from corridor.events.models import OutboxEvent
from corridor.events.tasks import dispatch_event
from corridor.identity import services as identity
from corridor.notifications.models import EmailLog, Notification
from corridor.shipments.models import Shipment, TrackingLink
from corridor.shipments.services import compute_eta
from tests.support import ApiClient, World, client_for
from tests.test_logistics import PNG, SIGNATURE, Setup, deliver, dispatched, err, evidence, ok, post, s  # noqa: F401
from tests.test_tracking import backdate_session, ev, send

pytestmark = pytest.mark.django_db

GALAFI = (11.716, 41.836)  # border post on the Djibouti-Ethiopia road
ADDIS = (9.03, 38.74)


@pytest.fixture
def moving(s: Setup, world: World) -> tuple[dict[str, Any], dict[str, Any]]:
    """(shipment, started trip) - the shipment is in transit."""
    sh, t = dispatched(s)
    trip = ok(post(s.driver, f"/trips/{t['id']}/start"))
    backdate_session(world, trip["id"], 120)  # so test points can be spaced at realistic speeds
    return sh, trip


def border_checkpoint(s: Setup, *, verify: bool, name: str = "Galafi") -> dict[str, Any]:
    g = ok(
        post(
            s.ops,
            "/geofences",
            {
                "name": f"{name} post",
                "kind": "border",
                "center": {"lat": GALAFI[0], "lng": GALAFI[1]},
                "radius_m": 2000,
            },
        ),
        201,
    )
    assert g["verified"] is False and g["shape"] == "circle"
    if verify:
        ok(post(s.ops, f"/geofences/{g['id']}/verify"))
    cp: dict[str, Any] = ok(
        post(s.ops, "/checkpoints", {"geofence_id": g["id"], "name": name, "is_border": True}), 201
    )
    return cp


# --------------------------------------------------------------------------- geofences and checkpoints


def test_geofence_permissions_and_validation(s: Setup, world: World) -> None:
    body = {"name": "Port", "kind": "port", "center": {"lat": 11.6, "lng": 43.1}, "radius_m": 500}
    err(post(s.disp, "/geofences", body), 403, "forbidden")  # dispatchers cannot draw geofences
    code, _ = post(s.ops, "/geofences", {**body, "polygon": [{"lat": 1, "lng": 1}] * 3})
    assert code == 422  # either a circle or a polygon, never both
    ok(post(s.ops, "/geofences", body), 201)
    err(post(s.ops, "/geofences", body), 409, "conflict")
    assert [g["name"] for g in ok(client_for(world.m("bravo_admin")).get("/geofences"))] == []  # isolation


def test_verified_border_entry_moves_to_at_border_but_never_clears(
    s: Setup, moving: Any, world: World
) -> None:
    sh, trip = moving
    cp = border_checkpoint(s, verify=True)
    now = timezone.now()
    send(s, ev(trip, s, at=now - timedelta(minutes=90), lat=11.80, lng=41.95))  # outside, ~15 km away
    send(s, ev(trip, s, at=now - timedelta(minutes=60), lat=GALAFI[0], lng=GALAFI[1]))  # inside
    shipment = ok(s.ops.get(f"/shipments/{sh['id']}"))
    assert shipment["status"] == "at_border"  # arrival, by the system
    events = ok(s.ops.get(f"/shipments/{sh['id']}/events"))
    arrived = [e for e in events if e["type"] == "border_arrived"]
    assert len(arrived) == 1 and arrived[0]["payload"]["source"] == "geofence"
    assert not [e for e in events if e["type"] == "border_cleared"]  # hard rule 8

    visits = ok(s.ops.get(f"/trips/{trip['id']}/checkpoint-visits"))
    assert len(visits) == 1 and visits[0]["checkpoint_id"] == cp["id"] and visits[0]["exited_at"] is None
    send(s, ev(trip, s, at=now - timedelta(minutes=30), lat=11.70, lng=41.70))  # left the area
    visits = ok(s.ops.get(f"/trips/{trip['id']}/checkpoint-visits"))
    assert visits[0]["exited_at"] is not None
    assert ok(s.ops.get(f"/shipments/{sh['id']}"))["status"] == "at_border"  # still waits for clearance
    with tenant_context(world.tenants["alpha"]):
        assert OutboxEvent.objects.filter(type="checkpoint.reached", aggregate_id=trip["id"]).count() == 1
        assert OutboxEvent.objects.filter(type="border.arrived", aggregate_id=sh["id"]).count() == 1


def test_unverified_border_only_records_the_visit(s: Setup, moving: Any) -> None:
    sh, trip = moving
    border_checkpoint(s, verify=False)
    send(s, ev(trip, s, at=timezone.now() - timedelta(minutes=30), lat=GALAFI[0], lng=GALAFI[1]))
    assert ok(s.ops.get(f"/shipments/{sh['id']}"))["status"] == "in_transit"
    visits = ok(s.ops.get(f"/trips/{trip['id']}/checkpoint-visits"))
    assert len(visits) == 1 and visits[0]["geofence_verified"] is False


def test_untrusted_or_older_points_never_trigger_checkpoints(s: Setup, moving: Any) -> None:
    sh, trip = moving
    border_checkpoint(s, verify=True)
    now = timezone.now()
    send(s, ev(trip, s, at=now - timedelta(minutes=60), lat=11.80, lng=41.95))
    # low accuracy: stored, never trusted
    send(s, ev(trip, s, at=now - timedelta(minutes=30), lat=GALAFI[0], lng=GALAFI[1], accuracy=900))
    # older than the latest point: stored as history, never trusted
    send(s, ev(trip, s, at=now - timedelta(minutes=90), lat=GALAFI[0], lng=GALAFI[1]))
    # impossible speed (Djibouti city -> Galafi in a minute): never trusted
    send(s, ev(trip, s, at=now - timedelta(minutes=59), lat=GALAFI[0], lng=GALAFI[1]))
    assert ok(s.ops.get(f"/trips/{trip['id']}/checkpoint-visits")) == []
    assert ok(s.ops.get(f"/shipments/{sh['id']}"))["status"] == "in_transit"


# --------------------------------------------------------------------------- ETA


def test_compute_eta_is_deterministic() -> None:
    at = timezone.now()
    eta, km = compute_eta(
        lat=GALAFI[0], lng=GALAFI[1], recorded_at=at, dest_lat=ADDIS[0], dest_lng=ADDIS[1], at_border=False
    )
    assert 500 < km < 700  # straight line ~ 430 km x 1.3
    assert eta == at + timedelta(hours=km / 45.0) or abs((eta - at).total_seconds() - km / 45 * 3600) < 400
    eta_b, _ = compute_eta(
        lat=GALAFI[0], lng=GALAFI[1], recorded_at=at, dest_lat=ADDIS[0], dest_lng=ADDIS[1], at_border=True
    )
    assert eta_b - eta == timedelta(hours=6)
    arrived, zero = compute_eta(
        lat=ADDIS[0], lng=ADDIS[1], recorded_at=at, dest_lat=ADDIS[0], dest_lng=ADDIS[1], at_border=False
    )
    assert zero == 0.0 and arrived == at


def test_eta_follows_newer_points_only(s: Setup, moving: Any, world: World) -> None:
    sh, trip = moving
    send(s, ev(trip, s, at=timezone.now() - timedelta(minutes=90)))
    assert (
        ok(s.ops.get(f"/shipments/{sh['id']}"))["eta_method"] == "unavailable_no_destination"
    )  # never guessed
    with tenant_context(world.tenants["alpha"]):
        Shipment.objects.filter(id=sh["id"]).update(destination_point=Point(ADDIS[1], ADDIS[0], srid=4326))
    newer = timezone.now() - timedelta(minutes=60)
    send(s, ev(trip, s, at=newer, lat=11.55, lng=43.0))
    first = ok(s.ops.get(f"/shipments/{sh['id']}"))
    assert first["eta_method"] == "deterministic_v1" and first["eta"] is not None
    assert first["eta_remaining_km"] > 0
    # An older point (stored as history) never moves the ETA.
    send(s, ev(trip, s, at=newer - timedelta(minutes=15), lat=11.57, lng=43.05))
    again = ok(s.ops.get(f"/shipments/{sh['id']}"))
    assert again["eta"] == first["eta"] and again["eta_basis_recorded_at"] == first["eta_basis_recorded_at"]


# --------------------------------------------------------------------------- tracking links


def public(token: str) -> tuple[int, Any]:
    return ApiClient(None).get(f"/public/tracking/{token}")


def test_tracking_link_lifecycle(s: Setup, moving: Any, world: World) -> None:
    sh, trip = moving
    send(s, ev(trip, s, at=timezone.now() - timedelta(minutes=1), lat=11.59412, lng=43.14876))
    finance = client_for(world.m("alpha_finance"))
    err(post(finance, f"/shipments/{sh['id']}/tracking-links", {}), 403, "forbidden")
    link = ok(
        post(s.ops, f"/shipments/{sh['id']}/tracking-links", {"label": "Consignee", "expires_in_days": 7}),
        201,
    )
    token = link["token"]
    assert link["state"] == "active" and len(token) >= 40
    with tenant_context(world.tenants["alpha"]):
        stored = TrackingLink.objects.get(id=link["id"])
        assert stored.token_hash != token and len(stored.token_hash) == 64  # only the hash is stored
    assert "token" not in ok(s.ops.get(f"/shipments/{sh['id']}/tracking-links"))[0]

    code, view = public(token)
    assert code == 200, view
    assert view["reference"] == sh["reference"] and view["status"] == "in_transit"
    pos = view["position"]
    assert pos["latitude"] == 11.59 and pos["longitude"] == 43.15 and pos["precision_km"] == 1.0  # coarse
    assert {"recorded_at", "received_at", "freshness"} <= set(pos)  # never "live" without times
    flat = str(view)
    for secret in ("driver", "plate", "vehicle", s.vehicle_id, s.driver_id, "DJ 1001"):
        assert secret not in flat
    assert all(set(t) == {"label", "at"} for t in view["timeline"])  # no actors or reasons

    err(post(s.ops, f"/tracking-links/{link['id']}/revoke", {"reason": ""}), 422, "validation_error")
    revoked = ok(post(s.ops, f"/tracking-links/{link['id']}/revoke", {"reason": "Sent to the wrong person"}))
    assert revoked["state"] == "revoked"
    err(public(token), 404, "not_found")


def test_tracking_link_allowlist_expiry_and_unknown_tokens(s: Setup, moving: Any, world: World) -> None:
    sh, _ = moving
    link = ok(post(s.ops, f"/shipments/{sh['id']}/tracking-links", {"allowed_fields": ["status"]}), 201)
    view = ok(public(link["token"]))
    assert set(view) == {"reference", "status", "is_delayed"}  # nothing beyond the allowlist
    err(public("x" * 43), 404, "not_found")  # unknown token: same answer as revoked/expired
    err(public("short"), 404, "not_found")
    with tenant_context(world.tenants["alpha"]):
        TrackingLink.objects.filter(id=link["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    err(public(link["token"]), 404, "not_found")
    code, _ = post(s.ops, f"/shipments/{sh['id']}/tracking-links", {"expires_in_days": 365})
    assert code == 422  # links live 90 days at most


def test_tracking_links_are_tenant_isolated(s: Setup, moving: Any, world: World) -> None:
    sh, _ = moving
    link = ok(post(s.ops, f"/shipments/{sh['id']}/tracking-links", {}), 201)
    bravo = client_for(world.m("bravo_admin"))
    err(bravo.get(f"/shipments/{sh['id']}/tracking-links"), 404, "not_found")
    err(post(bravo, f"/shipments/{sh['id']}/tracking-links", {}), 404, "not_found")
    err(post(bravo, f"/tracking-links/{link['id']}/revoke", {"reason": "not mine"}), 404, "not_found")
    assert ok(public(link["token"]))["reference"] == sh["reference"]  # still alive


def test_public_rate_limit() -> None:
    bucket, key = f"test-{uuid.uuid4().hex}", "203.0.113.9"
    for _ in range(3):
        ratelimit.check(bucket, key, limit=3)
    with pytest.raises(ApiError) as exc:
        ratelimit.check(bucket, key, limit=3)
    assert exc.value.status == 429


# --------------------------------------------------------------------------- proof of delivery and documents


def upload(c: ApiClient, shipment_id: str, kind: str, data: bytes, name: str = "f") -> tuple[int, Any]:
    return c.upload(
        f"/shipments/{shipment_id}/documents",
        {"kind": kind, "file": SimpleUploadedFile(name, data)},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )


def test_uploads_are_checked_by_content(s: Setup, moving: Any) -> None:
    sh, _ = moving
    err(
        upload(s.driver, sh["id"], "delivery_photo", b"<script>alert(1)</script>", "x.png"),
        422,
        "invalid_file",
    )
    err(
        upload(s.driver, sh["id"], "delivery_photo", b"%PDF-1.7 ..."), 422, "invalid_file"
    )  # photo must be image
    err(
        upload(s.driver, sh["id"], "delivery_photo", b"\xff\xd8\xff" + b"0" * (10 * 1024 * 1024)),
        422,
        "invalid_file",
    )
    bad_sigs = [
        b"not json",
        b'{"width": 10, "height": 10, "strokes": [[[1, 1], [2, "<svg>"]]]}',
        b'{"width": 10, "height": 10, "strokes": [], "extra": 1}',
        b'{"width": 10, "height": 10, "strokes": [[[1, 1]]]}',
    ]
    for sig in bad_sigs:
        err(upload(s.driver, sh["id"], "delivery_signature", sig), 422, "invalid_signature")
    doc = ok(upload(s.driver, sh["id"], "delivery_photo", PNG, "door.png"), 201)
    assert doc["content_type"] == "image/png" and doc["visibility"] == "internal"
    code, body = s.ops.get(f"/documents/{doc['id']}/content")
    assert code == 200 and body == PNG


def test_delivery_needs_evidence_of_this_shipment(s: Setup, moving: Any, world: World) -> None:
    sh, _ = moving
    body = {"recipient_name": "TEST Recipient"}
    code, _ = post(s.driver, f"/shipments/{sh['id']}/deliver", body)
    assert code == 422  # photo and signature are required
    proof = evidence(s.driver, sh["id"])
    swapped = {**body, "photo_ids": [proof["signature_id"]], "signature_id": proof["photo_ids"][0]}
    err(post(s.driver, f"/shipments/{sh['id']}/deliver", swapped), 422, "invalid_evidence")
    err(
        post(s.driver, f"/shipments/{sh['id']}/deliver", {**body, **proof, "photo_ids": [str(uuid.uuid4())]}),
        422,
        "invalid_evidence",
    )
    assert ok(s.ops.get(f"/shipments/{sh['id']}"))["status"] == "in_transit"  # nothing changed
    delivered = ok(post(s.driver, f"/shipments/{sh['id']}/deliver", {**body, **proof}))
    assert delivered["status"] == "delivered"
    event = next(e for e in ok(s.ops.get(f"/shipments/{sh['id']}/events")) if e["type"] == "delivered")
    assert event["payload"]["signature_id"] == proof["signature_id"]

    # The customer sees the proof of delivery, never internal paperwork.
    ok(upload(s.ops, sh["id"], "paperwork", b"%PDF-1.7 internal"), 201)
    member = world.m("alpha_customer")
    with tenant_context(world.tenants["alpha"]):
        identity.attach_customer_profile(member.membership_id, uuid.UUID(s.customer_id))
    portal = client_for(member)
    kinds = sorted(d["kind"] for d in ok(portal.get(f"/shipments/{sh['id']}/documents")))
    assert kinds == ["delivery_photo", "delivery_signature"]
    code, _ = upload(portal, sh["id"], "paperwork", b"%PDF-1.7 x")
    assert code == 403
    err(client_for(world.m("bravo_admin")).get(f"/shipments/{sh['id']}/documents"), 404, "not_found")


# --------------------------------------------------------------------------- notifications


def run_outbox(world: World, event_type: str) -> list[int]:
    """Deliver matching outbox rows to the handlers as the worker would (twice: at-least-once)."""
    with tenant_context(world.tenants["alpha"]):
        rows = list(OutboxEvent.objects.filter(type=event_type).order_by("id"))
    counts = []
    for _ in range(2):
        for r in rows:
            counts.append(
                dispatch_event(
                    event_id=r.id,
                    tenant_id=str(r.tenant_id),
                    event_type=r.type,
                    aggregate_type=r.aggregate_type,
                    aggregate_id=r.aggregate_id,
                    payload=r.payload,
                )
            )
    return counts


def test_notifications_are_idempotent_and_email_is_suppressed(s: Setup, world: World) -> None:
    with tenant_context(world.tenants["alpha"]):
        from corridor.customers.models import Customer

        Customer.objects.filter(id=s.customer_id).update(email="consignee@example.invalid")
    sh, _ = dispatched(s)
    mail.outbox.clear()
    assert run_outbox(world, "shipment.dispatched")[0] >= 1
    with tenant_context(world.tenants["alpha"]):
        inbox_rows = Notification.objects.filter(kind="shipment.dispatched")
        users = set(inbox_rows.values_list("recipient_user_id", flat=True))
        assert inbox_rows.count() == len(users) >= 1  # once per person despite two deliveries
        assert world.m("alpha_ops_manager").user_id in users
        assert world.m("alpha_customer").user_id not in users and world.m("alpha_driver").user_id not in users
        logs = list(EmailLog.objects.filter(kind="shipment.dispatched"))
        assert len(logs) == 1 and logs[0].status == "suppressed"  # no real email without approval
    assert len(mail.outbox) == 1 and sh["reference"] in mail.outbox[0].subject

    ops = s.ops
    page = ok(ops.get("/notifications"))
    assert page["unread"] >= 1 and page["items"][0]["title"].endswith("dispatched")
    ok(post(ops, f"/notifications/{page['items'][0]['id']}/read"))
    err(
        post(client_for(world.m("alpha_dispatcher")), f"/notifications/{page['items'][0]['id']}/read"),
        404,
        "not_found",
    )  # someone else's notification
    ok(post(ops, "/notifications/read-all"))
    assert ok(ops.get("/notifications?unread=true"))["items"] == []
