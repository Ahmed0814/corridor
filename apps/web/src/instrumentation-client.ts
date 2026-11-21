import * as Sentry from "@sentry/nextjs";

import { sentryDataCollection } from "@/lib/sentry-options";

// Browser-side Sentry. Inactive unless NEXT_PUBLIC_SENTRY_DSN is set at build time.
if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
  Sentry.init({
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "development",
    tracesSampleRate: 0,
    dataCollection: sentryDataCollection,
  });
}

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
