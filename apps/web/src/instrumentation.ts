import * as Sentry from "@sentry/nextjs";

import { sentryDataCollection } from "@/lib/sentry-options";

// Server-side Sentry. Inactive unless SENTRY_DSN is set (no DSN is committed anywhere).
export async function register() {
  if (!process.env.SENTRY_DSN) return;
  Sentry.init({
    dsn: process.env.SENTRY_DSN,
    environment: process.env.SENTRY_ENVIRONMENT ?? "development",
    release: process.env.RELEASE,
    tracesSampleRate: 0,
    dataCollection: sentryDataCollection,
  });
}

export const onRequestError = Sentry.captureRequestError;
