import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { parseReadiness } from "@/lib/health";

import { ReadinessList } from "./readiness-list";

const labels = {
  api: "API",
  database: "Database",
  redis: "Redis",
  ok: "OK",
  down: "Unavailable",
  unreachable: "API unreachable",
};

describe("parseReadiness", () => {
  it("treats a 200 with both checks as healthy", () => {
    const r = parseReadiness(200, { status: "ok", checks: { database: true, redis: true } }, "abc");
    expect(r).toEqual({ reachable: true, ok: true, checks: { database: true, redis: true }, requestId: "abc" });
  });

  it("treats malformed bodies as failing checks", () => {
    const r = parseReadiness(503, "garbage", null);
    expect(r).toEqual({ reachable: true, ok: false, checks: { database: false, redis: false }, requestId: null });
  });
});

describe("ReadinessList", () => {
  it("shows each dependency with its state", () => {
    render(
      <ReadinessList readiness={parseReadiness(503, { checks: { database: true, redis: false } }, null)} labels={labels} />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[1]).toHaveTextContent("DatabaseOK");
    expect(items[2]).toHaveTextContent("RedisUnavailable");
    expect(screen.getByRole("list")).toHaveAttribute("data-readiness", "degraded");
  });

  it("announces an unreachable API as an alert", () => {
    render(<ReadinessList readiness={{ reachable: false }} labels={labels} />);
    expect(screen.getByRole("alert")).toHaveTextContent("API unreachable");
    expect(screen.getByRole("alert")).toHaveAttribute("data-readiness", "unreachable");
  });
});
