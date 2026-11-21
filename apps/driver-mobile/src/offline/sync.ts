// Sync engine: uploads queued GPS events in batches and applies acknowledgements (MASTER_PROMPT §4.2).
//
//  * Batches of at most 500 (the API limit), oldest first.
//  * Network failures (offline, timeout, response lost after the server stored the batch) leave the
//    events pending; the next attempt re-sends them and the server reports them as "duplicate",
//    so they are deleted then. Nothing is lost and nothing is stored twice.
//  * Exponential backoff with jitter between failed attempts, capped at 5 minutes.
//  * A batch refused as malformed (HTTP 422) is split in halves until the bad event is isolated and
//    marked rejected locally; the rest still goes through.
//  * 401 stops syncing until the driver signs in again (events stay queued).
import type { LocationQueue } from "./queue";
import type { Clock, Transport, TransportError } from "./types";

export const MAX_BATCH = 500;
export const BASE_DELAY_MS = 2_000;
export const MAX_DELAY_MS = 5 * 60_000;

export type SyncStatus = "idle" | "syncing" | "offline" | "auth_required" | "error";

export type SyncState = {
  status: SyncStatus;
  pending: number;
  rejected: number;
  lastSuccessAt: number | null;
  lastError: string | null;
  consecutiveFailures: number;
  nextRetryAt: number | null;
};

export type SyncOutcome = { sent: number; deleted: number; rejected: number; requests: number; stoppedBy: SyncStatus | null };

/** Delay before retry n (1-based): 2 s, 4 s, 8 s, … capped at 5 min, with ±20 % jitter. */
export function backoffDelay(failures: number, random: () => number = Math.random): number {
  const raw = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** Math.max(0, failures - 1));
  return Math.round(raw * (0.8 + 0.4 * random()));
}

function asTransportError(e: unknown): TransportError {
  if (e && typeof e === "object" && "kind" in e) return e as TransportError;
  return { kind: "network", message: e instanceof Error ? e.message : String(e) };
}

export class SyncEngine {
  private running = false;
  private state: SyncState;
  private readonly queue: LocationQueue;
  private readonly transport: Transport;
  private readonly clock: Clock;
  private readonly onState: (s: SyncState) => void;
  private readonly batchSize: number;

  constructor(
    queue: LocationQueue,
    transport: Transport,
    clock: Clock,
    onState: (s: SyncState) => void = () => {},
    batchSize = MAX_BATCH,
  ) {
    this.queue = queue;
    this.transport = transport;
    this.clock = clock;
    this.onState = onState;
    this.batchSize = batchSize;
    const counts = queue.counts();
    const last = queue.getMeta("last_sync_success_at");
    this.state = {
      status: "idle",
      ...counts,
      lastSuccessAt: last ? Number(last) : null,
      lastError: null,
      consecutiveFailures: 0,
      nextRetryAt: null,
    };
  }

  getState(): SyncState {
    return { ...this.state, ...this.queue.counts() };
  }

  private emit(patch: Partial<SyncState>): void {
    this.state = { ...this.state, ...patch, ...this.queue.counts() };
    this.onState(this.getState());
  }

  /** Is a retry due (no backoff pending)? */
  canAttempt(): boolean {
    return this.state.nextRetryAt === null || this.clock.now() >= this.state.nextRetryAt;
  }

  /**
   * Send everything that is pending, batch after batch, until the queue is empty or a failure stops
   * the round. Safe to call often (from the background task, on reconnect, on a timer): concurrent
   * calls are ignored while a round is running.
   */
  async syncOnce(): Promise<SyncOutcome> {
    const outcome: SyncOutcome = { sent: 0, deleted: 0, rejected: 0, requests: 0, stoppedBy: null };
    if (this.running || this.state.status === "auth_required") {
      outcome.stoppedBy = this.state.status === "auth_required" ? "auth_required" : null;
      return outcome;
    }
    this.running = true;
    try {
      this.emit({ status: "syncing" });
      for (;;) {
        const batch = this.queue.nextBatch(this.batchSize);
        if (batch.length === 0) break;
        const stop = await this.sendWithIsolation(batch, outcome);
        if (stop) {
          outcome.stoppedBy = stop;
          return outcome;
        }
      }
      const now = this.clock.now();
      this.queue.setMeta("last_sync_success_at", String(now));
      this.emit({ status: "idle", lastSuccessAt: now, lastError: null, consecutiveFailures: 0, nextRetryAt: null });
      return outcome;
    } finally {
      this.running = false;
    }
  }

  /** Returns a status that stops the round, or null to continue. */
  private async sendWithIsolation(
    batch: Parameters<Transport["sendBatch"]>[0],
    outcome: SyncOutcome,
  ): Promise<SyncStatus | null> {
    this.queue.markAttempt(batch.map((e) => e.event_id));
    outcome.requests += 1;
    try {
      const result = await this.transport.sendBatch(batch);
      outcome.sent += batch.length;
      const applied = this.queue.applyAck(result);
      outcome.deleted += applied.deleted;
      outcome.rejected += applied.rejected;
      this.emit({ status: "syncing" });
      return null;
    } catch (e) {
      const err = asTransportError(e);
      if (err.kind === "http" && err.status === 422) {
        // The whole request was refused as malformed: isolate the offending event(s).
        if (batch.length === 1) {
          this.queue.rejectLocally(batch[0].event_id, `invalid_payload${err.code ? `:${err.code}` : ""}`);
          outcome.rejected += 1;
          return null;
        }
        const mid = Math.ceil(batch.length / 2);
        return (await this.sendWithIsolation(batch.slice(0, mid), outcome)) ?? this.sendWithIsolation(batch.slice(mid), outcome);
      }
      if (err.kind === "http" && (err.status === 401 || err.status === 403)) {
        this.emit({ status: "auth_required", lastError: err.code ?? `http_${err.status}` });
        return "auth_required";
      }
      const failures = this.state.consecutiveFailures + 1;
      const offline = err.kind === "network";
      this.emit({
        status: offline ? "offline" : "error",
        lastError: err.kind === "network" ? err.message : `http_${err.status}`,
        consecutiveFailures: failures,
        nextRetryAt: this.clock.now() + backoffDelay(failures),
      });
      return offline ? "offline" : "error";
    }
  }

  /** Clear the auth stop after the driver signs in again. */
  resumeAfterSignIn(): void {
    if (this.state.status === "auth_required") this.emit({ status: "idle", lastError: null });
  }

  /** Forget the backoff (e.g. the network just came back). */
  resetBackoff(): void {
    this.emit({ nextRetryAt: null, consecutiveFailures: 0 });
  }
}
