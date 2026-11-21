"""Regenerate the role → permission table in docs/security/security-model.md from
corridor/identity/permissions.py (the single source of truth, D-008).

    python scripts/gen_permission_matrix.py           # rewrite the table
    python scripts/gen_permission_matrix.py --check   # exit 1 if the doc is out of date (CI/test)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corridor.identity.permissions import PERMISSIONS, ROLES  # noqa: E402

DOC = ROOT.parent / "docs" / "security" / "security-model.md"
BEGIN = "<!-- BEGIN GENERATED PERMISSION MATRIX (backend/scripts/gen_permission_matrix.py) -->"
END = "<!-- END GENERATED PERMISSION MATRIX -->"


def render() -> str:
    roles = list(ROLES.values())
    header = "| Permission | " + " | ".join(r.name for r in roles) + " |"
    sep = "|---|" + "---|" * len(roles)
    lines = [header, sep]
    for code, description in PERMISSIONS.items():
        cells = " | ".join("✓" if code in r.permissions else "–" for r in roles)  # noqa: RUF001
        lines.append(f"| `{code}` {description} | {cells} |")
    lines += [
        "",
        "| Role | MFA required | Scope | App clients |",
        "|---|---|---|---|",
        *[
            f"| {r.name} (`{r.code}`) | {'yes' if r.requires_mfa else 'no'} | {r.scope.value} | "
            + ", ".join(sorted(c.value for c in r.clients))
            + " |"
            for r in roles
        ],
    ]
    return "\n".join([BEGIN, *lines, END])


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        sys.stderr.write(f"markers not found in {DOC}{os.linesep}")
        return 1
    before, rest = text.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    updated = before + render() + after
    if "--check" in sys.argv:
        if updated != text:
            sys.stderr.write(f"{DOC} is out of date: run python scripts/gen_permission_matrix.py{os.linesep}")
            return 1
        return 0
    DOC.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
