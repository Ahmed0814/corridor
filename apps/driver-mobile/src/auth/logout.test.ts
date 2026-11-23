/// <reference types="node" />
import assert from "node:assert/strict";
import { test } from "node:test";

import { isWrongAccount, logoutUrl } from "./session.ts";

test("logout URL for Cognito and the local issuer", () => {
  assert.equal(
    logoutUrl("https://x.auth.ca-central-1.amazoncognito.com/oauth2/authorize", "abc", "corridor-driver://auth/callback"),
    "https://x.auth.ca-central-1.amazoncognito.com/logout?client_id=abc&logout_uri=corridor-driver%3A%2F%2Fauth%2Fcallback",
  );
  assert.equal(
    logoutUrl("http://10.0.2.2:8000/dev-auth/authorize", "local-driver-mobile", "corridor-driver://auth/callback"),
    "http://10.0.2.2:8000/dev-auth/logout?client_id=local-driver-mobile&logout_uri=corridor-driver%3A%2F%2Fauth%2Fcallback",
  );
});

test("wrong-account errors", () => {
  assert.equal(isWrongAccount("wrong_client"), true);
  assert.equal(isWrongAccount("no_membership"), true);
  assert.equal(isWrongAccount("unreachable"), false);
  assert.equal(isWrongAccount(null), false);
});
