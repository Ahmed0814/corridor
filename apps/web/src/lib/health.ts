export type ReadinessChecks = { database: boolean; redis: boolean };
export type Readiness =
  | { reachable: true; ok: boolean; checks: ReadinessChecks; requestId: string | null }
  | { reachable: false };

/** Parse the backend /healthz/ready response. Anything unexpected counts as "not ok". */
export function parseReadiness(status: number, body: unknown, requestId: string | null): Readiness {
  const checks = (body as { checks?: Partial<ReadinessChecks> } | null)?.checks ?? {};
  return {
    reachable: true,
    ok: status === 200,
    checks: { database: checks.database === true, redis: checks.redis === true },
    requestId,
  };
}

export async function fetchReadiness(baseUrl: string, timeoutMs = 3000): Promise<Readiness> {
  try {
    const response = await fetch(`${baseUrl}/healthz/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    const body: unknown = await response.json().catch(() => null);
    return parseReadiness(response.status, body, response.headers.get("x-request-id"));
  } catch {
    return { reachable: false };
  }
}
