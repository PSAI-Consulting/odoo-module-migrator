#!/usr/bin/env python3
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Extract migration rule candidates from the Odoo git repositories.

Re-run it for each new Odoo version (21.0...): it only reads local bare
repositories (``git show`` / ``git log``, no checkout) and writes YAML files
in the format of ``odoo_module_migrate/migration_scripts/<type>/migrate_XXX_YYY``.

    python tools/extract_changes.py modules --from 19.0 --to 20.0 \\
        --repo D:/Odoo/.repos/odoo.git@addons \\
        --repo D:/Odoo/.repos/enterprise.git \\
        --repo D:/Odoo/.repos/design-themes.git \\
        --openupgrade D:/Odoo/local-addons/OdooOCA/OpenUpgrade

Every generated rule carries its source (commit or apriori.py) as a comment.
"""

import argparse
import ast
import collections
import pathlib
import re
import subprocess
import sys

MANIFEST_RE = re.compile(r"^(?:(?P<prefix>.+)/)?(?P<module>[^/]+)/__manifest__\.py$")


def git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))
    return result.stdout.decode("utf-8", "replace")


def resolve_ref(repo, branch):
    for ref in (branch, f"origin/{branch}", f"refs/remotes/origin/{branch}"):
        try:
            git(repo, "rev-parse", "--verify", "--quiet", ref)
            return ref
        except RuntimeError:
            continue
    raise SystemExit(f"Branch {branch} not found in {repo}")


def list_modules(repo, ref, prefix):
    """{module_name: module_path} of the modules (dirs with a manifest)."""
    args = ["ls-tree", "-r", "--name-only", ref]
    if prefix:
        args += ["--", prefix]
    result = {}
    for line in git(repo, *args).splitlines():
        match = MANIFEST_RE.match(line)
        if match and (match["prefix"] or "") == (prefix or ""):
            result[match["module"]] = line.rsplit("/", 1)[0]
    return result


def deletion_commit(repo, ref_from, ref_to, module_path):
    out = git(
        repo, "log", "--diff-filter=D", "--format=%h%x09%s", "-1",
        f"{ref_from}..{ref_to}", "--", f"{module_path}/__manifest__.py",
    )
    if not out.strip():
        return None, ""
    sha, _, subject = out.strip().partition("\t")
    return sha, subject


def moved_to(repo, sha, module_path, prefix):
    """Module that received most of the files of `module_path` in `sha`."""
    out = git(repo, "show", "-M", "--name-status", "--format=", sha)
    targets = collections.Counter()
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R") and parts[1].startswith(module_path + "/"):
            new = parts[2][len(prefix) + 1:] if prefix else parts[2]
            targets[new.split("/", 1)[0]] += 1
    if not targets:
        return None
    module, _count = targets.most_common(1)[0]
    return module


SUBJECT_PATTERNS = [
    # "[REF] hr: merge hr_org_chart into hr", "merge module in hr"
    re.compile(r"\b(?:merge|move|moved|fold)\w*\b.*?\b(?:into|in|to|with)\s+`?(?P<target>[a-z][a-z0-9_]+)`?"),
    # "[MOV] website_sale_collect(_wishlist->{})": module merged into the base one
    re.compile(r"\b(?P<target>[a-z][a-z0-9_]+)\((?P<suffix>_?[a-z0-9_]+)->\{\}\)"),
]


def target_from_subject(subject, module, after):
    for pattern in SUBJECT_PATTERNS:
        for match in pattern.finditer(subject):
            target = match["target"]
            if "suffix" in pattern.groupindex and module not in (
                target + match["suffix"], target + "_" + match["suffix"].lstrip("_")
            ):
                continue
            if target in after and target != module:
                return target
    return None


def load_curated(path):
    """Hand-written rules (curated.yaml): they win over generated ones."""
    if not path or not pathlib.Path(path).exists():
        return set()
    import yaml

    return {item[0] for item in yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or []}


def resolve_chains(rules):
    """a -> b and b -> c (same step) gives a -> c."""
    targets = {old: new for old, action, new, _ in rules if action in ("merged", "renamed")}
    result = []
    for old, action, new, source in rules:
        seen = {old}
        while new in targets and new not in seen:
            seen.add(new)
            new = targets[new]
        result.append((old, action, new, source))
    return result


def load_apriori(openupgrade, version):
    """renamed_modules / merged_modules of OpenUpgrade for the target version."""
    if not openupgrade:
        return {}, {}
    repo = pathlib.Path(openupgrade)
    try:
        ref = resolve_ref(repo, version)
        source = git(repo, "show", f"{ref}:openupgrade_scripts/apriori.py")
    except (RuntimeError, SystemExit):
        print(f"# OpenUpgrade {version}: no apriori.py", file=sys.stderr)
        return {}, {}
    result = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            name = node.targets[0].id
            if name in ("renamed_modules", "merged_modules"):
                result[name] = ast.literal_eval(node.value)
    return result.get("renamed_modules", {}), result.get("merged_modules", {})


def extract_modules(args):
    repos = []
    for spec in args.repo:
        path, _, prefix = spec.partition("@")
        repos.append((pathlib.Path(path), prefix.strip("/")))

    before, after, where = {}, {}, {}
    for repo, prefix in repos:
        ref_from, ref_to = resolve_ref(repo, args.from_version), resolve_ref(repo, args.to_version)
        mods_from = list_modules(repo, ref_from, prefix)
        mods_to = list_modules(repo, ref_to, prefix)
        before.update(mods_from)
        after.update(mods_to)
        for name, path in mods_from.items():
            where[name] = (repo, prefix, ref_from, ref_to, path)

    renamed, merged = load_apriori(args.openupgrade, args.to_version)
    ou_source = f"OpenUpgrade {args.to_version} openupgrade_scripts/apriori.py"

    rules = []
    for name in sorted(set(before) - set(after)):
        repo, prefix, ref_from, ref_to, path = where[name]
        source_repo = repo.name.removesuffix(".git")
        if name in renamed:
            rules.append((name, "renamed", renamed[name], ou_source))
            continue
        if name in merged:
            rules.append((name, "merged", merged[name], ou_source))
            continue
        sha, subject = deletion_commit(repo, ref_from, ref_to, path)
        source = f"{source_repo} {sha} {subject!r}" if sha else f"{source_repo} {args.to_version}"
        target = moved_to(repo, sha, path, prefix) if sha else None
        if not (target and target in after):
            target = target_from_subject(subject, name, after)
        if target and target in after:
            action = "merged" if target in before else "renamed"
            rules.append((name, action, target, source))
        else:
            rules.append((name, "removed", None, source))

    # OCA modules (not in the Odoo repositories) known by OpenUpgrade
    for old, new in sorted(renamed.items()):
        if old not in before:
            rules.append((old, "renamed", new, ou_source + " (OCA)"))
    for old, new in sorted(merged.items()):
        if old not in before:
            rules.append((old, "merged", new, ou_source + " (OCA)"))

    curated = load_curated(args.curated)
    rules = [rule for rule in resolve_chains(rules) if rule[0] not in curated]

    lines = [
        f"# Modules removed / renamed / merged between {args.from_version} and {args.to_version}",
        "# Generated by tools/extract_changes.py modules: review before committing.",
        "# Format: [old_module, removed|renamed|merged, new_module]",
        "# Corrections go in curated.yaml (same folder): its modules are skipped here.",
    ]
    for old, action, new, source in rules:
        item = f'["{old}", "{action}"' + (f', "{new}"' if new else "") + "]"
        lines.append(f"- {item}  # {source}")
    text = "\n".join(lines) + "\n"
    if args.output:
        out = pathlib.Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"{len(rules)} rules written to {out}", file=sys.stderr)
    else:
        sys.stdout.write(text)


DEFAULT_MODEL_PREFIXES = (
    "res.", "product.", "sale.", "purchase.", "stock.", "account.", "mrp.", "uom.",
    "hr.", "project.", "crm.", "mail.", "ir.", "delivery.", "quality.", "repair.",
    "website.", "pos.", "calendar.", "utm.", "payment.", "fleet.", "maintenance.",
)


def _write_rules(path, header, rows, fmt):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {line}" for line in header] + [fmt(row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(rows)} rules written to {path}", file=sys.stderr)


def _q(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def extract_fields(args):
    import extract_fields as ef

    prefixes = tuple(args.models.split(",")) if args.models else DEFAULT_MODEL_PREFIXES

    def models_filter(model):
        return model.startswith(prefixes)

    step = f"migrate_{args.from_version.replace('.', '')}_{args.to_version.replace('.', '')}"
    out = pathlib.Path(args.output_dir)
    renamed_fields, renamed_models, removed_fields, removed_models = [], [], [], []
    candidates = []

    if args.openupgrade:
        ou = pathlib.Path(args.openupgrade)
        try:
            ref = resolve_ref(ou, args.to_version)
            renamed_fields, renamed_models, removed_fields, removed_models = (
                ef.openupgrade_changes(ou, ref, models_filter)
            )
        except SystemExit:
            pass
        if removed_fields and args.repo:
            # "DEL" in an analysis means "this module does not define the field
            # anymore": keep it only if no module of the target defines it
            target = ef.target_fields(
                [pathlib.Path(spec.partition("@")[0]) for spec in args.repo],
                lambda repo: resolve_ref(repo, args.to_version),
            )
            before = len(removed_fields)
            removed_fields = [r for r in removed_fields if r[1] not in target.get(r[0], ())]
            removed_models = [r for r in removed_models if r[0] not in target]
            print(f"{before - len(removed_fields)} 'DEL' fields still defined in "
                  f"{args.to_version}: skipped", file=sys.stderr)
    if not renamed_fields and not removed_fields:
        # No OpenUpgrade analysis for this version: compare the sources
        repos = [pathlib.Path(spec.partition("@")[0]) for spec in args.repo]
        removed_fields, candidates = ef.source_changes(
            repos,
            lambda repo: resolve_ref(repo, args.from_version),
            lambda repo: resolve_ref(repo, args.to_version),
            models_filter,
        )
        removed_fields = [
            (m, f, s) for m, f, s in removed_fields
            if (m, f) not in {(c[0], c[1]) for c in candidates}
        ]
        # "rename X to Y" in the commit message: confirmed
        confirmed, candidates = ef.promote_candidates(candidates)
        renamed_fields = renamed_fields + confirmed

    header = [
        f"Generated by tools/extract_changes.py fields --from {args.from_version} --to {args.to_version}",
        "Do not edit: write corrections in another file of this folder.",
    ]
    _write_rules(
        out / "renamed_fields" / step / "generated.yaml",
        header + ["Format: [model, old_field, new_field, source]"],
        ef.dedupe(renamed_fields, lambda r: r[:2]),
        lambda r: f"- [{_q(r[0])}, {_q(r[1])}, {_q(r[2])}, {_q(r[3])}]",
    )
    _write_rules(
        out / "renamed_fields" / step / "candidates.yaml",
        header + [
            "Rename CANDIDATES found in the sources (field removed in the commit",
            "that adds a field of the same type): check them, then uncomment.",
        ],
        ef.dedupe(candidates, lambda r: r[:2]),
        lambda r: f"# - [{_q(r[0])}, {_q(r[1])}, {_q(r[2])}, {_q(r[3])}]",
    )
    _write_rules(
        out / "removed_fields" / step / "generated.yaml",
        header + ["Format: [model, field, source]"],
        ef.dedupe(removed_fields, lambda r: r[:2]),
        lambda r: f"- [{_q(r[0])}, {_q(r[1])}, {_q(r[2])}]",
    )
    if renamed_models:
        _write_rules(
            out / "renamed_models" / step / "generated.yaml",
            header + ["Format: [old_model, new_model, source]"],
            ef.dedupe(renamed_models, lambda r: r[0]),
            lambda r: f"- [{_q(r[0])}, {_q(r[1])}, {_q(r[2])}]",
        )
    if removed_models:
        _write_rules(
            out / "removed_models" / step / "generated.yaml",
            header + ["Format: [model, source]"],
            ef.dedupe(removed_models, lambda r: r[0]),
            lambda r: f"- [{_q(r[0])}, {_q(r[1])}]",
        )


def extract_api(args):
    import extract_api as ea

    repo = pathlib.Path(args.repo)
    removed_modules, removed_methods, removed_functions, deprecations = ea.api_changes(
        repo, resolve_ref(repo, args.from_version), resolve_ref(repo, args.to_version)
    )
    lines = [
        f"# Core API candidates {args.from_version} -> {args.to_version}"
        " (tools/extract_changes.py api): REVIEW before using them as rules.",
        "", "# Python modules removed:",
        *[f"#   {m}" for m in removed_modules],
        "", "# BaseModel methods removed:",
        *[f"#   {m}" for m in removed_methods],
        "", "# Functions / classes removed (module where they were defined):",
        *[f"#   {name}  ({', '.join(mods)})" for name, mods in removed_functions],
        "", f"# New deprecation messages in {args.to_version}:",
        *[f"#   {loc}: {msg}" for loc, msg in deprecations],
    ]
    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"{len(removed_modules)} modules, {len(removed_methods)} methods, "
        f"{len(removed_functions)} functions, {len(deprecations)} deprecations -> {out}",
        file=sys.stderr,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    api = sub.add_parser("api", help="core API candidates (methods, functions, modules)")
    api.add_argument("--from", dest="from_version", required=True)
    api.add_argument("--to", dest="to_version", required=True)
    api.add_argument("--repo", required=True, help="odoo bare repository")
    api.add_argument("--output", required=True)
    flds = sub.add_parser("fields", help="renamed / removed fields and models")
    flds.add_argument("--from", dest="from_version", required=True)
    flds.add_argument("--to", dest="to_version", required=True)
    flds.add_argument("--repo", action="append", default=[],
                      help="bare repository (sources compared when OpenUpgrade has no data)")
    flds.add_argument("--openupgrade", help="OpenUpgrade clone")
    flds.add_argument("--models", help="comma separated model prefixes (default: main apps)")
    flds.add_argument("--output-dir", required=True, help="odoo_module_migrate/migration_scripts")
    mods = sub.add_parser("modules", help="removed / renamed / merged modules")
    mods.add_argument("--from", dest="from_version", required=True)
    mods.add_argument("--to", dest="to_version", required=True)
    mods.add_argument("--repo", action="append", required=True,
                      help="bare repository[@addons_prefix], repeatable")
    mods.add_argument("--openupgrade", help="OpenUpgrade clone (for apriori.py)")
    mods.add_argument("--output", help="YAML file (default: stdout)")
    mods.add_argument("--curated", help="hand-written rules to skip (default: curated.yaml next to --output)")
    args = parser.parse_args(argv)
    if args.command == "modules":
        if args.output and not args.curated:
            args.curated = str(pathlib.Path(args.output).with_name("curated.yaml"))
        extract_modules(args)
    elif args.command == "fields":
        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        extract_fields(args)
    elif args.command == "api":
        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        extract_api(args)


if __name__ == "__main__":
    main()
