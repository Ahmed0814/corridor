import { Badge } from "@/components/ui/badge";
import type { Readiness } from "@/lib/health";

export type ReadinessLabels = {
  api: string;
  database: string;
  redis: string;
  ok: string;
  down: string;
  unreachable: string;
};

function Row({ name, ok, labels }: { name: string; ok: boolean; labels: ReadinessLabels }) {
  return (
    <li className="flex items-center justify-between border-b py-2 last:border-b-0">
      <span>{name}</span>
      <Badge variant={ok ? "secondary" : "destructive"}>{ok ? labels.ok : labels.down}</Badge>
    </li>
  );
}

export function ReadinessList({ readiness, labels }: { readiness: Readiness; labels: ReadinessLabels }) {
  if (!readiness.reachable) {
    return (
      <p role="alert" data-readiness="unreachable" className="text-destructive">
        {labels.unreachable}
      </p>
    );
  }
  return (
    <ul aria-label={labels.api} data-readiness={readiness.ok ? "ok" : "degraded"}>
      <Row name={labels.api} ok={true} labels={labels} />
      <Row name={labels.database} ok={readiness.checks.database} labels={labels} />
      <Row name={labels.redis} ok={readiness.checks.redis} labels={labels} />
    </ul>
  );
}
