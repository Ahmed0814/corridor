/// <reference types="node" />
// Offline behaviour (MASTER_PROMPT §8 "Offline"): network loss, local persistence, app restart,
// interrupted batch, acknowledgements, retry, duplicate prevention, reconnection, 10,000-event sync.
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import { LocationQueue } from "./queue.ts";
import { backoffDelay, MAX_DELAY_MS, SyncEngine } from "./sync.ts";
import { FakeServer, fakeClock, makeEvent, nodeDb, seeded } from "./testing.ts";

function setup(server = new FakeServer(), path = ":memory:") {
  const db = nodeDb(path);
  const queue = new LocationQueue(db);
  const clock = fakeClock();
  const engine = new SyncEngine(queue, server, clock);
  return { db, queue, clock, engine, server };
}

describe("local persistence", () => {
  it("saves every event before any network call", async () => {
    const { queue, server } = setup();
    for (let i = 0; i < 3; i++) queue.enqueue(makeEvent(i));
    assert.equal(server.requests, 0);
    assert.deepEqual(queue.counts(), { pending: 3, rejected: 0 });
  });

  it("never queues the same event twice", () => {
    const { queue } = setup();
    const e = makeEvent(1);
    assert.equal(queue.enqueue(e), true);
    assert.equal(queue.enqueue(e), false);
    assert.equal(queue.counts().pending, 1);
  });

  it("keeps the queue and sequence across an app restart (database closed and reopened)", async () => {
    const dir = mkdtempSync(join(tmpdir(), "corridor-queue-"));
    const file = join(dir, "queue.db");
    try {
      const first = setup(new FakeServer(), file);
      for (let i = 0; i < 5; i++) first.queue.enqueue(makeEvent(i));
      assert.equal(first.queue.nextSequence(), 1);
      assert.equal(first.queue.nextSequence(), 2);
      first.db.close(); // the OS killed the app

      const server = new FakeServer();
      const second = setup(server, file);
      assert.equal(second.queue.counts().pending, 5);
      assert.equal(second.queue.nextSequence(), 3); // continues, never reuses a sequence number
      await second.engine.syncOnce();
      assert.equal(server.stored.size, 5);
      assert.equal(second.queue.counts().pending, 0);
      second.db.close();
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("network loss and reconnection", () => {
  it("keeps events while offline, backs off, and delivers on reconnection", async () => {
    const { queue, engine, server, clock } = setup();
    for (let i = 0; i < 10; i++) queue.enqueue(makeEvent(i));
    server.mode = "drop";
    const out = await engine.syncOnce();
    assert.equal(out.stoppedBy, "offline");
    const s = engine.getState();
    assert.equal(s.status, "offline");
    assert.equal(s.pending, 10);
    assert.ok(s.nextRetryAt !== null && s.nextRetryAt > clock.now());
    assert.equal(engine.canAttempt(), false);

    server.mode = "ok"; // network is back
    engine.resetBackoff();
    await engine.syncOnce();
    assert.equal(server.stored.size, 10);
    assert.equal(engine.getState().status, "idle");
    assert.equal(engine.getState().pending, 0);
    assert.equal(engine.getState().lastSuccessAt, clock.now());
  });

  it("server errors are retried later without losing anything", async () => {
    const { queue, engine, server } = setup();
    queue.enqueue(makeEvent(1));
    server.mode = "http500";
    assert.equal((await engine.syncOnce()).stoppedBy, "error");
    assert.equal(queue.counts().pending, 1);
    server.mode = "ok";
    engine.resetBackoff();
    await engine.syncOnce();
    assert.equal(server.stored.size, 1);
  });
});

describe("interrupted batch and acknowledgements", () => {
  it("a batch stored by the server whose response was lost is acknowledged as duplicate on retry", async () => {
    const { queue, engine, server } = setup();
    for (let i = 0; i < 20; i++) queue.enqueue(makeEvent(i));
    server.mode = "lose_response";
    await engine.syncOnce();
    assert.equal(server.stored.size, 20); // the server has them...
    assert.equal(queue.counts().pending, 20); // ...but the phone did not get the ack, so it keeps them
    server.mode = "ok";
    engine.resetBackoff();
    const out = await engine.syncOnce();
    assert.equal(out.deleted, 20);
    assert.equal(queue.counts().pending, 0);
    assert.equal(server.stored.size, 20); // stored exactly once
  });

  it("deletes accepted and duplicate events, keeps rejected ones for review and never resends them", async () => {
    const { queue, engine, server } = setup();
    const events = Array.from({ length: 6 }, (_, i) => makeEvent(i));
    queue.enqueueMany(events);
    server.rejectIds.add(events[2].event_id);
    server.rejectIds.add(events[4].event_id);
    await engine.syncOnce();
    assert.deepEqual(queue.counts(), { pending: 0, rejected: 2 });
    assert.deepEqual(queue.rejected().map((r) => r.reason), ["no_session", "no_session"]);
    const before = server.requests;
    await engine.syncOnce();
    assert.equal(server.requests, before); // nothing pending: no request
  });

  it("isolates a malformed event (HTTP 422) and still delivers the rest", async () => {
    const { queue, engine, server } = setup();
    const events = Array.from({ length: 40 }, (_, i) => makeEvent(i));
    queue.enqueueMany(events);
    server.poisonIds.add(events[17].event_id);
    await engine.syncOnce();
    assert.equal(server.stored.size, 39);
    assert.deepEqual(queue.counts(), { pending: 0, rejected: 1 });
    assert.match(queue.rejected()[0].reason, /^invalid_payload/);
  });

  it("stops on 401 until the driver signs in again, keeping every event", async () => {
    const { queue, engine, server } = setup();
    queue.enqueue(makeEvent(1));
    server.mode = "http401";
    assert.equal((await engine.syncOnce()).stoppedBy, "auth_required");
    server.mode = "ok";
    assert.equal((await engine.syncOnce()).stoppedBy, "auth_required"); // still stopped
    assert.equal(queue.counts().pending, 1);
    engine.resumeAfterSignIn();
    await engine.syncOnce();
    assert.equal(server.stored.size, 1);
  });

  it("ignores a second sync started while one is running (no double send)", async () => {
    const { queue, engine, server } = setup();
    for (let i = 0; i < 5; i++) queue.enqueue(makeEvent(i));
    await Promise.all([engine.syncOnce(), engine.syncOnce()]);
    assert.equal(server.requests, 1);
    assert.equal(server.stored.size, 5);
  });
});

describe("retry backoff", () => {
  it("grows exponentially with jitter and is capped at 5 minutes", () => {
    assert.equal(backoffDelay(1, () => 0.5), 2_000);
    assert.equal(backoffDelay(2, () => 0.5), 4_000);
    assert.equal(backoffDelay(5, () => 0.5), 32_000);
    assert.equal(backoffDelay(50, () => 0.5), MAX_DELAY_MS);
    assert.ok(backoffDelay(3, () => 0) >= 6_400 && backoffDelay(3, () => 0.999) <= 9_600);
  });
});

describe("10,000-event queue sync", () => {
  it("drains 10,000 events through an unreliable network with no loss and no duplicates", async () => {
    const server = new FakeServer(seeded(42));
    server.dropRate = 0.15; // request never reaches the server
    server.loseRate = 0.15; // server stores the batch, response is lost
    const { queue, engine, clock } = setup(server);
    const started = performance.now();
    const events = Array.from({ length: 10_000 }, (_, i) => makeEvent(i));
    queue.enqueueMany(events);
    assert.equal(queue.counts().pending, 10_000);

    let rounds = 0;
    while (queue.counts().pending > 0 && rounds < 500) {
      rounds += 1;
      await engine.syncOnce();
      clock.advance(5 * 60_000); // wait out any backoff
    }
    const elapsed = performance.now() - started;
    assert.equal(queue.counts().pending, 0);
    assert.equal(queue.counts().rejected, 0);
    assert.equal(server.stored.size, 10_000); // every event exactly once on the server
    assert.ok(server.maxBatchSeen <= 500);
    const ids = new Set(events.map((e) => `${e.device_id}:${e.event_id}`));
    assert.ok([...server.stored.keys()].every((k) => ids.has(k)));
    console.log(
      `[10k sync] ${server.requests} requests, ${rounds} sync rounds, max batch ${server.maxBatchSeen}, ${elapsed.toFixed(0)} ms`,
    );
  });
});
