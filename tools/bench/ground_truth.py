#!/usr/bin/env python3
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Ground truth: compare the migrator with migrations made by hand (OCA).

For each module present (installable) in both branches of an OCA repository,
the FROM version is exported, migrated with odoo_module_migrate, and compared
with the TO version written by the OCA contributors:

    python tools/bench/ground_truth.py --from 17.0 --to 18.0 \\
        --repo /tmp/odoo-src/sale-workflow --repo /tmp/odoo-src/partner-contact \\
        --limit 15 --work /tmp/gt --output /tmp/gt/RESULTS.md

Per module: similarity of the lines (difflib, blank lines and trailing spaces
ignored, README / i18n / static/description skipped) before migration
(original vs OCA) and after (migrated vs OCA): the gain is what the migrator
did right. The most frequent lines changed by the OCA but not by the
migrator are listed: they are leads for missing rules (to be proven in the
Odoo sources before becoming rules, see docs/).
"""

import argparse
import ast
import collections
import difflib
import io
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parents[2]  # repository root
SUFFIXES = (".py", ".xml", ".csv", ".js")
SKIP_RE = re.compile(r"(^|/)(i18n|i18n_extra|static/description|readme|README[^/]*)(/|$)")


def git(repo, *args, binary=False):
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout
    return out if binary else out.decode("utf-8", "replace")


def resolve(repo, ref):
    for candidate in (ref, f"origin/{ref}"):
        if subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", candidate],
                          capture_output=True).returncode == 0:
            return candidate
    raise SystemExit(f"{ref} not found in {repo}")


def modules(repo, ref):
    """{module: manifest} of the installable modules of a branch."""
    result = {}
    for path in git(repo, "ls-tree", "--name-only", "-r", ref).splitlines():
        parts = path.split("/")
        # __openerp__.py up to 9.0
        if len(parts) == 2 and parts[1] in ("__manifest__.py", "__openerp__.py"):
            try:
                manifest = ast.literal_eval(git(repo, "show", f"{ref}:{path}").lstrip())
            except (ValueError, SyntaxError, subprocess.CalledProcessError):
                continue
            if isinstance(manifest, dict) and manifest.get("installable", True):
                result[parts[0]] = manifest
    return result


def export(repo, ref, module, target):
    data = git(repo, "archive", "--format=tar", ref, module, binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(target, filter="data")


def lines(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def files(module_dir):
    return {
        p.relative_to(module_dir).as_posix(): p
        for p in module_dir.rglob("*")
        if p.is_file() and p.suffix in SUFFIXES
        and not SKIP_RE.search(p.relative_to(module_dir).as_posix())
    }


def similarity(dir_a, dir_b):
    """(matching lines, total lines) between two versions of a module."""
    fa, fb = files(dir_a), files(dir_b)
    same = total = 0
    for name in fa.keys() | fb.keys():
        la = lines(fa[name]) if name in fa else []
        lb = lines(fb[name]) if name in fb else []
        matcher = difflib.SequenceMatcher(None, la, lb, autojunk=False)
        same += sum(block.size for block in matcher.get_matching_blocks())
        total += max(len(la), len(lb))
    return same, total


def missed(original, migrated, expected):
    """Lines the OCA changed (absent from its version) that the migrator kept."""
    result = collections.Counter()
    fo, fm, fe = files(original), files(migrated), files(expected)
    for name in fo.keys() & fm.keys() & fe.keys():
        kept = set(lines(fm[name])) & set(lines(fo[name]))
        for line in kept - set(lines(fe[name])):
            result[re.sub(r"\s+", " ", line.strip())] += 1
    return result


def migrate(directory, names, version_from, version_to):
    subprocess.run(
        [sys.executable, "-m", "odoo_module_migrate", "--directory", str(directory),
         "--modules", ",".join(names), "--init-version-name", version_from,
         "--target-version-name", version_to, "--no-commit", "--no-pre-commit",
         "--log-level", "ERROR"],
        cwd=ROOT, check=False, capture_output=True,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="version_from", required=True)
    parser.add_argument("--to", dest="version_to", required=True)
    parser.add_argument("--repo", action="append", required=True, help="OCA clone, repeatable")
    parser.add_argument("--modules", help="comma separated module names (default: all common modules)")
    parser.add_argument("--limit", type=int, help="modules per repository")
    parser.add_argument("--work", required=True, help="work folder (emptied)")
    parser.add_argument("--output", help="Markdown report (default: <work>/RESULTS.md)")
    args = parser.parse_args(argv)

    work = pathlib.Path(args.work)
    shutil.rmtree(work, ignore_errors=True)
    rows, leads = [], collections.Counter()
    wanted = set(args.modules.split(",")) if args.modules else None
    for repo in map(pathlib.Path, args.repo):
        ref_from, ref_to = resolve(repo, args.version_from), resolve(repo, args.version_to)
        before, after = modules(repo, ref_from), modules(repo, ref_to)
        names = sorted(
            n for n in before.keys() & after.keys()
            if str(after[n].get("version", "")).startswith(args.version_to)
            and (wanted is None or n in wanted)
        )[: args.limit]
        if not names:
            continue
        base = work / repo.name
        for name in names:
            export(repo, ref_from, name, base / "original")
            export(repo, ref_from, name, base / "migrated")
            export(repo, ref_to, name, base / "expected")
        migrate(base / "migrated", names, args.version_from, args.version_to)
        for name in names:
            original, migrated, expected = (base / k / name for k in ("original", "migrated", "expected"))
            same_before, total_before = similarity(original, expected)
            same_after, total_after = similarity(migrated, expected)
            rows.append((repo.name, name, same_before / (total_before or 1), same_after / (total_after or 1),
                         total_after))
            leads.update(missed(original, migrated, expected))
        print(f"{repo.name}: {len(names)} modules", file=sys.stderr)

    out = pathlib.Path(args.output) if args.output else work / "RESULTS.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    report = [
        f"# Vérité terrain OCA {args.version_from} → {args.version_to}",
        "",
        "Lignes identiques à la version migrée à la main par l'OCA (README, i18n,",
        "static/description ignorés ; lignes vides et espaces de fin ignorés).",
        "",
        "| Dépôt | Module | Avant | Après | Gain | Lignes |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for repo_name, name, before, after, total in rows:
        report.append(f"| {repo_name} | {name} | {before:.1%} | {after:.1%} | {after - before:+.1%} | {total} |")
    if rows:
        mean_before = sum(r[2] for r in rows) / len(rows)
        mean_after = sum(r[3] for r in rows) / len(rows)
        report.append(f"| **moyenne** | {len(rows)} modules | {mean_before:.1%} | {mean_after:.1%} "
                      f"| {mean_after - mean_before:+.1%} | |")
    report += [
        "",
        "## Lignes modifiées par l'OCA mais pas par le migrator (les plus fréquentes)",
        "",
        "Pistes de règles manquantes, à prouver dans les sources d'Odoo avant d'en faire des règles.",
        "",
        "| Occurrences | Ligne |",
        "|---:|---|",
    ]
    for line, count in leads.most_common(40):
        cell = line[:120].replace("|", "\\|")
        report.append(f"| {count} | `{cell}` |")
    out.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"{len(rows)} modules -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
