// expo-sqlite adapter for the SqlDb interface (the queue's storage on the phone).
import * as SQLite from "expo-sqlite";

import type { SqlDb } from "./types";

export function openQueueDb(name = "corridor-queue.db"): SqlDb {
  const db = SQLite.openDatabaseSync(name);
  db.execSync("PRAGMA journal_mode = WAL;"); // recommended by Expo; safer concurrent reads
  let depth = 0;
  return {
    exec: (sql) => db.execSync(sql),
    run: (sql, params = []) => ({ changes: db.runSync(sql, params).changes }),
    all: <T,>(sql: string, params: (string | number | null)[] = []) => db.getAllSync<T>(sql, params),
    transaction: <T,>(fn: () => T): T => {
      if (depth > 0) return fn();
      depth += 1;
      try {
        let out!: T;
        db.withTransactionSync(() => {
          out = fn();
        });
        return out;
      } finally {
        depth -= 1;
      }
    },
  };
}
