/// <reference types="node" />
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// Expo inlines EXPO_PUBLIC_* only when written literally as process.env.EXPO_PUBLIC_X. Any other
// form ships undefined values and the app silently talks to the emulator defaults.
test("build-time settings are read with the literal process.env.EXPO_PUBLIC_* form", () => {
  const src = readFileSync(new URL("./config.ts", import.meta.url), "utf8");
  const code = src.replace(/\/\/.*$/gm, "");
  assert.doesNotMatch(code, /=\s*process\.env\s*;/, "process.env must not be aliased");
  assert.doesNotMatch(code, /\{[^}]*\}\s*=\s*process\.env/, "process.env must not be destructured");
  assert.doesNotMatch(code, /process\.env\[/, "process.env must not be indexed");
  for (const key of ["EXPO_PUBLIC_API_BASE_URL", "EXPO_PUBLIC_AUTH_CLIENT_ID", "EXPO_PUBLIC_AUTH_AUTHORIZE_URL", "EXPO_PUBLIC_AUTH_TOKEN_URL"]) {
    assert.match(code, new RegExp(`process\\.env\\.${key}\\b`), `${key} must be read literally`);
  }
});
