#!/usr/bin/env python3
"""Turn reviewed field metadata candidates into evidence-backed v2 rules.

The extractors deliberately emit candidates.  This helper only promotes a
candidate when the field definition exists at both branch tips and a commit in
the migration range changes that exact field in the cited file.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

import yaml

REPOS = {
    "odoo.git": ("odoo", Path(r"D:\Odoo\.repos\odoo.git")),
    "enterprise.git": ("enterprise", Path(r"D:\Odoo\.repos\enterprise.git")),
    "design-themes.git": ("odoo", Path(r"D:\Odoo\.repos\design-themes.git")),
}


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "--git-dir", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))
    return result.stdout.decode("utf-8", "replace")


def definition(repo: Path, ref: str, path: str, field: str) -> tuple[int, str] | None:
    text = git(repo, "show", f"{ref}:{path}", check=False)
    if not text:
        return None
    pattern = re.compile(
        rf"^(?P<indent>\s*){re.escape(field)}\s*=\s*fields\.(?P<type>\w+)\(",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return None
    line = text.count("\n", 0, match.start()) + 1
    # Capture the complete declaration conservatively through the closing line.
    lines = text.splitlines()
    start = line - 1
    depth = 0
    captured = []
    for current in lines[start : start + 40]:
        captured.append(current.strip())
        depth += current.count("(") - current.count(")")
        if depth <= 0:
            break
    return line, " ".join(captured)


def metadata_value(kind: str, declaration: str, property_name: str = "") -> str:
    if kind == "field_type":
        match = re.search(r"fields\.(\w+)\(", declaration)
        return match.group(1) if match else ""
    if property_name == "store":
        return "True" if re.search(r"\bstore\s*=\s*True\b", declaration) else "False"
    return ""


def change_commit(
    repo: Path,
    old_ref: str,
    new_ref: str,
    path: str,
    field: str,
    kind: str,
    old_value: str,
    new_value: str,
    property_name: str = "",
) -> tuple[str, str] | None:
    pattern = rf"^\s*{re.escape(field)}\s*=\s*fields\."
    rows = git(
        repo,
        "log",
        "--reverse",
        "--format=%H%x09%s",
        f"-G{pattern}",
        f"{old_ref}..{new_ref}",
        "--",
        path,
        check=False,
    ).splitlines()
    for row in rows:
        sha, _, title = row.partition("\t")
        before = definition(repo, f"{sha}^", path, field)
        after = definition(repo, sha, path, field)
        if not before or not after:
            continue
        if metadata_value(kind, before[1], property_name) == old_value and metadata_value(
            kind, after[1], property_name
        ) == new_value:
            return sha, title
    return None


def source_parts(source: str) -> tuple[str, str]:
    repo_name, _tip, path = source.split(" ", 2)
    return repo_name, path


def render_rule(kind: str, row: list[str], source: str, old_version: str, new_version: str):
    repo_name, path = source_parts(source)
    if repo_name not in REPOS:
        return None, f"unsupported repository {repo_name}"
    repository, repo = REPOS[repo_name]
    model, field = row[0], row[1]
    old_def = definition(repo, old_version, path, field)
    new_def = definition(repo, new_version, path, field)
    if not old_def or not new_def:
        return None, "field definition is not present in the cited file at both branch tips"
    property_name = row[2] if kind == "field_property" else ""
    old_value = str(row[3] if kind == "field_property" else row[2])
    new_value = str(row[4] if kind == "field_property" else row[3])
    commit = change_commit(
        repo, old_version, new_version, path, field, kind, old_value, new_value, property_name
    )
    if not commit:
        return None, "no field-definition commit found in the migration range"
    sha, title = commit
    short = sha[:12]
    common = {
        "schema_version": 2,
        "kind": kind,
        "model": model,
        "field": field,
        "confidence": "verified",
        "evidence": [{
            "repository": repository,
            "commit": short,
            "title": title,
            "file": path,
            "lines": f"{old_version}:{old_def[0]}; {new_version}:{new_def[0]}",
            "note": f"{old_version}: {old_def[1]} | {new_version}: {new_def[1]}",
        }],
    }
    if kind == "field_type":
        common.update(old_type=row[2], new_type=row[3])
        common["message"] = f"{repository} {short}: {model}.{field} changed from {row[2]} to {row[3]}"
    else:
        common.update(property=row[2], old_value=str(row[3]), new_value=str(row[4]))
        common["message"] = (
            f"{repository} {short}: {model}.{field} {row[2]} changed from {row[3]} to {row[4]}"
        )
    return common, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    rejected = []
    promoted = 0
    for old, new in (("16.0", "17.0"), ("17.0", "18.0"), ("18.0", "19.0"), ("19.0", "20.0")):
        step = f"migrate_{old.replace('.', '').zfill(3)}_{new.replace('.', '').zfill(3)}"
        for category, kind, candidate_prefix in (
            ("field_types", "field_type", "lotb-field-types"),
            ("field_properties", "field_property", "lotb-field-properties"),
        ):
            candidate = args.root / f"{candidate_prefix}-{step}.yaml"
            rows = yaml.safe_load(candidate.read_text(encoding="utf-8")) or []
            existing_path = (
                args.root / "odoo_module_migrate" / "migration_scripts" / category / step / "curated.yaml"
            )
            existing = yaml.safe_load(existing_path.read_text(encoding="utf-8")) or [] if existing_path.exists() else []
            existing_keys = {
                (entry.get("model"), entry.get("field"), entry.get("property") if kind == "field_property" else None)
                for entry in existing
                if isinstance(entry, dict)
            }
            rules = []
            for row in rows:
                row_key = (row[0], row[1], row[2] if kind == "field_property" else None)
                if row_key in existing_keys:
                    continue
                source = row[-1]
                rule, reason = render_rule(kind, row, source, old, new)
                if rule:
                    rules.append(rule)
                    promoted += 1
                else:
                    rejected.append({"step": step, "kind": kind, "candidate": row[:-1], "source": source, "reason": reason})
            output = (
                args.root
                / "odoo_module_migrate"
                / "migration_scripts"
                / category
                / step
                / "curated_metadata.yaml"
            )
            if rules:
                output.parent.mkdir(parents=True, exist_ok=True)
                header = "# Verified from both branch tips and the changing commit; generated candidates remain non-applicable.\n"
                output.write_text(
                    header + yaml.safe_dump(rules, allow_unicode=True, sort_keys=False, width=120),
                    encoding="utf-8",
                )
    report = args.root / "lotb-field-metadata-rejected.yaml"
    report.write_text(yaml.safe_dump(rejected, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
    print(f"promoted={promoted} rejected={len(rejected)} report={report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
