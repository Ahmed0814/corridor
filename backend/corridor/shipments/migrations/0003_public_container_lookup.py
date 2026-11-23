"""Public "track a container" lookup (DECISIONS D-075).

A visitor gives the container number AND the shipment reference. This SECURITY DEFINER function
returns (tenant_id, shipment_id) only when both match one shipment of an active company that is on
the road or recently delivered. The container number alone is never enough: container numbers are
printed on the boxes. The owner needs read policies because FORCE RLS applies to it too (D-058).
"""

from django.db import migrations

SQL = """
CREATE POLICY lookup_owner_read ON shipments FOR SELECT TO corridor_owner USING (true);
CREATE POLICY lookup_owner_read ON shipment_containers FOR SELECT TO corridor_owner USING (true);
CREATE POLICY lookup_owner_read ON containers FOR SELECT TO corridor_owner USING (true);
CREATE FUNCTION public_find_shipment(p_container text, p_reference text)
    RETURNS TABLE (tenant_id uuid, shipment_id uuid)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$fn$
    SELECT s.tenant_id, s.id
    FROM shipments s
    JOIN tenants t ON t.id = s.tenant_id AND t.status = 'active'
    JOIN shipment_containers sc ON sc.shipment_id = s.id AND sc.tenant_id = s.tenant_id
    JOIN containers c ON c.id = sc.container_id AND c.tenant_id = s.tenant_id
    WHERE upper(s.reference) = upper(p_reference)
      AND c.number = upper(p_container)
      AND s.status IN ('dispatched', 'in_transit', 'at_border', 'delivery_failed', 'delivered')
      AND s.created_at > now() - interval '180 days'
      AND length(p_container) BETWEEN 11 AND 13
      AND length(p_reference) BETWEEN 3 AND 40
    LIMIT 2
$fn$;
REVOKE ALL ON FUNCTION public_find_shipment(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public_find_shipment(text, text) TO corridor_app;
"""
REVERSE = """
DROP FUNCTION IF EXISTS public_find_shipment(text, text);
DROP POLICY IF EXISTS lookup_owner_read ON containers;
DROP POLICY IF EXISTS lookup_owner_read ON shipment_containers;
DROP POLICY IF EXISTS lookup_owner_read ON shipments;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("shipments", "0002_shipment_eta_basis_recorded_at_and_more"),
        ("containers", "0001_initial"),
        ("tenants", "0002_member_read_policy"),
    ]

    operations = [migrations.RunSQL(SQL, REVERSE)]
