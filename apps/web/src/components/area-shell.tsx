import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";

/** Shared chrome for the three route groups (ops, portal, admin). */
export function AreaShell({
  title,
  scope,
  actions,
  children,
}: {
  title: string;
  scope: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="border-b">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-3 px-4 py-3">
          <Link href="/" className="font-semibold">
            Corridor
          </Link>
          <span className="text-muted-foreground">/</span>
          <span>{title}</span>
          <Badge variant="outline">{scope}</Badge>
          <div className="ms-auto">{actions}</div>
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
