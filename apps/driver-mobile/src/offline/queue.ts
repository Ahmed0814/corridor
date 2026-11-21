// Durable local queue of GPS events (MASTER_PROMPT §4.2):
//  * every event is saved locally BEFORE any network call;
//  * events are deleted only after the server acknowledges them (accepted or duplicate);
//  * rejected events are kept, marked, for review, and never resent;
//  * nothing is lost across app restarts (SQLite file).
import type { IngestResult, LocationEvent, SqlDb } from "./types";

export type QueueCounts = { pending: number; rejected: number };

export type RejectedRow = { event_id: string; reason: string; recorded_at: string };

const SCHEMA = `
CREATE TABLE IF NOT EXISTS location_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  trip_id TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  reason TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS location_queue_pending ON location_queue (status, id);
CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
`;

export class LocationQueue {
  private readonly db: SqlDb;
  private readonly now: () => number;

  constructor(db: SqlDb, now: () => number = Date.now) {
    this.db = db;
    this.now = now;
    this.db.exec(SCHEMA);
  }

  /** Save one event. Returns false if this event id is already queued (no duplicate rows). */
  enqueue(event: LocationEvent): boolean {
    const r = this.db.run(
      "INSERT OR IGNORE INTO location_queue (event_id, trip_id, recorded_at, payload, created_at) VALUES (?, ?, ?, ?, ?)",
      [event.event_id, event.trip_id, event.recorded_at, JSON.stringify(event), this.now()],
    );
    return r.changes === 1;
  }

  enqueueMany(events: LocationEvent[]): number {
    return this.db.transaction(() => events.reduce((n, e) => n + (this.enqueue(e) ? 1 : 0), 0));
  }

  /** Oldest pending events first (so the server sees them roughly in recorded order). */
  nextBatch(limit: number): LocationEvent[] {
    const rows = this.db.all<{ payload: string }>(
      "SELECT payload FROM location_queue WHERE status = 'pending' ORDER BY id LIMIT ?",
      [limit],
    );
    return rows.map((r) => JSON.parse(r.payload) as LocationEvent);
  }

  markAttempt(eventIds: string[]): void {
    if (eventIds.length === 0) return;
    this.db.run(
      `UPDATE location_queue SET attempts = attempts + 1 WHERE event_id IN (${eventIds.map(() => "?").join(",")})`,
      eventIds,
    );
  }

  /**
   * Apply the server's acknowledgement in one transaction. Accepted and duplicate events are deleted
   * (the server has them); rejected ones are kept with their reason. Ids the server did not mention
   * stay pending and are sent again.
   */
  applyAck(result: IngestResult): { deleted: number; rejected: number } {
    return this.db.transaction(() => {
      let deleted = 0;
      for (const id of [...result.accepted, ...result.duplicate]) {
        deleted += this.db.run("DELETE FROM location_queue WHERE event_id = ?", [id]).changes;
      }
      let rejected = 0;
      for (const r of result.rejected) {
        rejected += this.db.run(
          "UPDATE location_queue SET status = 'rejected', reason = ? WHERE event_id = ? AND status = 'pending'",
          [r.reason, r.event_id],
        ).changes;
      }
      return { deleted, rejected };
    });
  }

  /** Mark one event as rejected locally (e.g. the server refused it as malformed). */
  rejectLocally(eventId: string, reason: string): void {
    this.db.run("UPDATE location_queue SET status = 'rejected', reason = ? WHERE event_id = ?", [reason, eventId]);
  }

  counts(): QueueCounts {
    const rows = this.db.all<{ status: string; n: number }>(
      "SELECT status, COUNT(*) AS n FROM location_queue GROUP BY status",
    );
    const by = Object.fromEntries(rows.map((r) => [r.status, Number(r.n)]));
    return { pending: by.pending ?? 0, rejected: by.rejected ?? 0 };
  }

  rejected(limit = 50): RejectedRow[] {
    return this.db.all<RejectedRow>(
      "SELECT event_id, reason, recorded_at FROM location_queue WHERE status = 'rejected' ORDER BY id DESC LIMIT ?",
      [limit],
    );
  }

  // ---------------------------------------------------------------- small persistent key/value store

  getMeta(key: string): string | null {
    const rows = this.db.all<{ value: string }>("SELECT value FROM app_meta WHERE key = ?", [key]);
    return rows[0]?.value ?? null;
  }

  setMeta(key: string, value: string | null): void {
    if (value === null) this.db.run("DELETE FROM app_meta WHERE key = ?", [key]);
    else this.db.run("INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", [key, value]);
  }

  /** Monotonic per-device sequence number that survives restarts. */
  nextSequence(): number {
    return this.db.transaction(() => {
      const next = Number(this.getMeta("sequence") ?? "0") + 1;
      this.setMeta("sequence", String(next));
      return next;
    });
  }
}
