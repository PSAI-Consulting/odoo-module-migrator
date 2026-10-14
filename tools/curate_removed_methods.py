#!/usr/bin/env python3
"""Create evidence-backed text errors for removed BaseModel override methods."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

REPO = Path(r"D:\Odoo\.repos\odoo.git")


def git(*args: str, check: bool = False) -> str:
    result = subprocess.run(
        ["git", "--git-dir", str(REPO), *args], capture_output=True, check=False
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))
    return result.stdout.decode("utf-8", "replace")


def methods(path: Path) -> list[str]:
    result = []
    in_methods = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "# BaseModel methods removed:":
            in_methods = True
            continue
        if in_methods and line.startswith("# Functions / classes removed"):
            break
        if in_methods and line.startswith("#   "):
            result.append(line[4:].strip())
    return result


def locate(ref: str, method: str) -> tuple[str, int] | None:
    out = git("grep", "-n", "-E", rf"^[[:space:]]*def {re.escape(method)}\(", ref, "--", "odoo/*.py", "odoo/**/*.py")
    for line in out.splitlines():
        match = re.match(r"[^:]+:(.+?):(\d+):", line)
        if match:
            return match.group(1), int(match.group(2))
    return None


def deletion(old: str, new: str, path: str, method: str) -> tuple[str, str] | None:
    rows = git(
        "log", "--reverse", "--format=%H%x09%s", f"-Sdef {method}(", f"{old}..{new}", "--", path
    ).splitlines()
    for row in rows:
        sha, _, title = row.partition("\t")
        before = git("show", f"{sha}^:{path}")
        after = git("show", f"{sha}:{path}")
        pattern = re.compile(rf"^\s*def {re.escape(method)}\(", re.MULTILINE)
        if pattern.search(before) and not pattern.search(after):
            return sha, title
    return None


def main() -> int:
    root = Path.cwd()
    lot_c = []
    promoted = 0
    for old, new in (("16.0", "17.0"), ("17.0", "18.0"), ("18.0", "19.0"), ("19.0", "20.0")):
        step = f"migrate_{old.replace('.', '').zfill(3)}_{new.replace('.', '').zfill(3)}"
        candidate = root / f"lotb-api-{step}.yaml"
        entries = {}
        existing_text = "\n".join(
            p.read_text(encoding="utf-8", errors="replace")
            for p in (root / "odoo_module_migrate" / "migration_scripts" / "text_errors" / step).glob("*.yaml")
        )
        for method in methods(candidate):
            if method in existing_text:
                lot_c.append({"step": step, "method": method, "status": "already covered by a text rule"})
                continue
            location = locate(old, method)
            if not location:
                lot_c.append({"step": step, "method": method, "status": "old definition not uniquely located"})
                continue
            path, old_line = location
            commit = deletion(old, new, path, method)
            if not commit:
                lot_c.append({"step": step, "method": method, "file": path, "status": "no exact deletion commit"})
                continue
            sha, title = commit
            pattern = rf"\bdef\s+{re.escape(method)}\s*\("
            entries[pattern] = {
                "schema_version": 2,
                "kind": "text_error",
                "confidence": "verified",
                "evidence": {
                    "repository": "odoo",
                    "commit": sha[:12],
                    "title": title,
                    "file": path,
                    "lines": f"{old}:{old_line}; {new}:removed",
                },
                "message": f"[{new.split('.')[0]}] BaseModel.{method} was removed - odoo {sha[:12]} {title!r}",
            }
            promoted += 1
        if entries:
            output = (
                root / "odoo_module_migrate" / "migration_scripts" / "text_errors" / step / "curated_removed_methods.yaml"
            )
            output.write_text(
                "# Removed override methods verified against their deletion commit.\n"
                + yaml.safe_dump({".py": entries}, allow_unicode=True, sort_keys=False, width=120),
                encoding="utf-8",
            )
    (root / "lotb-methods-lot-c.yaml").write_text(
        yaml.safe_dump(lot_c, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8"
    )
    print(f"promoted={promoted} lot_c={len(lot_c)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
