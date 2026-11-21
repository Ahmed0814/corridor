import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";

/** Shared chrome for the three route groups. Each group gets its own auth scope in Phase 2. */
export function AreaShell({ title, scope, children }: { title: string; scope: string; children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="border-b">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3">
          <Link href="/" className="font-semibold">
            Corridor
          </Link>
          <span className="text-muted-foreground">/</span>
          <span>{title}</span>
          <Badge variant="outline" className="ms-auto">
            {scope}
          </Badge>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
    </div>
  );
}

export function NotBuiltNotice({ notBuilt, noData }: { notBuilt: string; noData: string }) {
  return (
    <div className="rounded-lg border border-dashed p-6 text-sm">
      <p>{notBuilt}</p>
      <p className="mt-2 text-muted-foreground">{noData}</p>
    </div>
  );
}
