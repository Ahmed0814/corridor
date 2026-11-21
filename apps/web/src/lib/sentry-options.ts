import type { DataCollection } from "@sentry/core";

// Strict data collection for every Sentry client (security-model.md §7).
// Bodies, cookies and query strings can carry PII or tracking tokens: never collected.
export const sentryDataCollection: DataCollection = {
  userInfo: false,
  cookies: false,
  httpHeaders: { allow: ["user-agent", "x-request-id", "accept-language"] },
  httpBodies: [],
  urlQueryParams: false,
};
