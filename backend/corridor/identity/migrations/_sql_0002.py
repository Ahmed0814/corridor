"""SQL for identity 0002 (kept apart for readability; the leading underscore keeps the
migration loader from treating this file as a migration)."""

USERS_RLS = """
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
-- Visible: myself (by id or by the Cognito sub being authenticated) and members of the current
-- tenant. Nothing else, so a user id from another tenant behaves as nonexistent.
CREATE POLICY users_visible ON users FOR SELECT TO corridor_app USING (
    id = app_user_id()
    OR cognito_sub = app_user_sub()
    OR EXISTS (SELECT 1 FROM tenant_memberships m
               WHERE m.user_id = users.id AND m.tenant_id = app_tenant_id())
);
CREATE POLICY users_self_update ON users FOR UPDATE TO corridor_app
    USING (id = app_user_id()) WITH CHECK (id = app_user_id());
-- SECURITY DEFINER functions owned by corridor_owner run under FORCE RLS too; this policy lets
-- them (and only roles acting as the owner, i.e. migrations) work on the table.
CREATE POLICY owner_definer ON users TO corridor_owner USING (true) WITH CHECK (true);
GRANT SELECT ON users TO corridor_app;
-- Column-level: identity fields, flags and the Cognito link are never writable by the app role.
GRANT UPDATE (display_name, mfa_verified_at, last_session_ref, last_tenant_id, last_login, updated_at)
    ON users TO corridor_app;
"""

USERS_RLS_REVERSE = """
REVOKE ALL ON users FROM corridor_app;
DROP POLICY IF EXISTS owner_definer ON users;
DROP POLICY IF EXISTS users_self_update ON users;
DROP POLICY IF EXISTS users_visible ON users;
ALTER TABLE users NO FORCE ROW LEVEL SECURITY;
ALTER TABLE users DISABLE ROW LEVEL SECURITY;
"""

# Invitations need to find-or-create a global user without letting the app role read users of
# other tenants (which would also leak whether an email is registered elsewhere). This function
# returns only the id. It requires a tenant context, so it is only callable while acting for a
# tenant; the caller then creates the membership under RLS.
UPSERT_USER = """
CREATE OR REPLACE FUNCTION identity_upsert_user(
    p_cognito_sub text, p_email text, p_phone text, p_display_name text
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_id uuid;
    v_sub text;
BEGIN
    IF app_tenant_id() IS NULL THEN
        RAISE EXCEPTION 'identity_upsert_user requires a tenant context' USING ERRCODE = '42501';
    END IF;
    IF p_cognito_sub IS NULL OR p_cognito_sub = '' THEN
        RAISE EXCEPTION 'cognito sub is required' USING ERRCODE = '22023';
    END IF;

    SELECT id, cognito_sub INTO v_id, v_sub FROM users WHERE cognito_sub = p_cognito_sub;
    IF v_id IS NULL AND p_email IS NOT NULL THEN
        SELECT id, cognito_sub INTO v_id, v_sub FROM users WHERE lower(email) = lower(p_email);
    END IF;
    IF v_id IS NULL AND p_phone IS NOT NULL THEN
        SELECT id, cognito_sub INTO v_id, v_sub FROM users WHERE phone_e164 = p_phone;
    END IF;

    IF v_id IS NULL THEN
        INSERT INTO users (id, password, is_superuser, cognito_sub, email, phone_e164, display_name,
                           is_platform_admin, is_staff, is_active, last_session_ref,
                           created_at, updated_at)
        VALUES (gen_random_uuid(), '!', false, p_cognito_sub, p_email, p_phone,
                coalesce(p_display_name, ''), false, false, true, '', now(), now())
        RETURNING id INTO v_id;
    ELSIF v_sub IS NULL THEN
        UPDATE users SET cognito_sub = p_cognito_sub, updated_at = now() WHERE id = v_id;
    ELSIF v_sub <> p_cognito_sub THEN
        RAISE EXCEPTION 'identity conflict for this email or phone' USING ERRCODE = '23505';
    END IF;
    RETURN v_id;
END
$$;
REVOKE ALL ON FUNCTION identity_upsert_user(text, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION identity_upsert_user(text, text, text, text) TO corridor_app;
"""

UPSERT_USER_REVERSE = "DROP FUNCTION IF EXISTS identity_upsert_user(text, text, text, text);"
