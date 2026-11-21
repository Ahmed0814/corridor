// One queue + sync engine per JS runtime, shared by the UI and the background location task.
// Both open the same SQLite file, so events captured in the background survive a restart.
import { openQueueDb } from "../offline/expoDb";
import { LocationQueue } from "../offline/queue";
import { SyncEngine, type SyncState } from "../offline/sync";
import { httpTransport } from "./transport";

type Listener = (s: SyncState) => void;

let queue: LocationQueue | null = null;
let engine: SyncEngine | null = null;
const listeners = new Set<Listener>();

const clock = { now: () => Date.now(), sleep: (ms: number) => new Promise<void>((r) => setTimeout(r, ms)) };

export function getQueue(): LocationQueue {
  if (!queue) queue = new LocationQueue(openQueueDb());
  return queue;
}

export function getEngine(): SyncEngine {
  if (!engine) engine = new SyncEngine(getQueue(), httpTransport, clock, (s) => listeners.forEach((l) => l(s)));
  return engine;
}

export function onSyncState(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Try to upload now unless a backoff is pending (called after captures, on reconnect, on a timer). */
export async function syncIfDue(force = false): Promise<void> {
  const e = getEngine();
  if (force) e.resetBackoff();
  if (!e.canAttempt()) return;
  try {
    await e.syncOnce();
  } catch {
    // The engine records failures in its state; never crash the background task.
  }
}
