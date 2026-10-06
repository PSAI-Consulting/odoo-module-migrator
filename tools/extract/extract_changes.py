#!/usr/bin/env python3
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Extract migration rule candidates from the Odoo git repositories.

Re-run it for each new Odoo version (21.0...): it only reads local bare
repositories (``git show`` / ``git log``, no checkout) and writes YAML files
in the format of ``odoo_module_migrate/migration_scripts/<type>/migrate_XXX_YYY``.

    python tools/extract/extract_changes.py modules --from 19.0 --to 20.0 \\
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

# __openerp__.py up to 9.0, __manifest__.py from 10.0
MANIFEST_RE = re.compile(r"^(?:(?P<prefix>.+)/)?(?P<module>[^/]+)/__(?:manifest|openerp)__\.py$")


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


def step_name(version_from, version_to):
    """migrate_090_100 (versions on 3 digits, as the migration scripts)."""
    def code(version):
        return version.replace(".", "").zfill(3)

    return f"migrate_{code(version_from)}_{code(version_to)}"


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
        f"{ref_from}..{ref_to}", "--", f"{module_path}/__manifest__.py", f"{module_path}/__openerp__.py",
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
        source = None
        # 14.0+ / 13.0 and before (fork of Odoo) / 9.0 (openerp namespace)
        for path in ("openupgrade_scripts/apriori.py",
                     "odoo/addons/openupgrade_records/lib/apriori.py",
                     "openerp/addons/openupgrade_records/lib/apriori.py"):
            try:
                source = git(repo, "show", f"{ref}:{path}")
                break
            except RuntimeError:
                continue
        if source is None:
            raise RuntimeError("no apriori.py")
    except (RuntimeError, SystemExit):
        print(f"# OpenUpgrade {version}: no apriori.py", file=sys.stderr)
        return {}, {}
    result = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            name = node.targets[0].id
            if name in ("renamed_modules", "merged_modules"):
                # keys with stray spaces exist ("gift_card " in OpenUpgrade 16.0)
                result[name] = {
                    str(k).strip(): v.strip() if isinstance(v, str) else v
                    for k, v in ast.literal_eval(node.value).items()
                }
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
    ou_source = f"OpenUpgrade {args.to_version} apriori.py"

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

    step = step_name(args.from_version, args.to_version)
    out = pathlib.Path(args.output_dir)
    renamed_fields, renamed_models, removed_fields, removed_models = [], [], [], []
    candidates, ou_candidates = [], []

    if args.openupgrade:
        ou = pathlib.Path(args.openupgrade)
        try:
            ref = resolve_ref(ou, args.to_version)
            renamed_fields, renamed_models, removed_fields, removed_models = (
                ef.openupgrade_changes(ou, ref, models_filter)
            )
        except SystemExit:
            pass
        if (removed_fields or renamed_fields) and args.repo:
            # "DEL" in an analysis means "this module does not define the field
            # anymore": keep it only if no module of the target defines it
            target = ef.target_fields(
                [pathlib.Path(spec.partition("@")[0]) for spec in args.repo],
                lambda repo: resolve_ref(repo, args.to_version),
            )
            # a data rename whose old field is still defined in the target is
            # not a code rename (renaming again would not be idempotent, e.g.
            # OpenUpgrade 16.0 mrp.workcenter capacity -> default_capacity):
            # candidate only
            kept = [r for r in renamed_fields if r[1] not in target.get(r[0], ())]
            ou_candidates += [
                (*r[:3], f"{r[3]} (old field still defined in {args.to_version})")
                for r in renamed_fields if r not in kept
            ]
            if len(kept) != len(renamed_fields):
                print(f"{len(renamed_fields) - len(kept)} renamed fields still defined in "
                      f"{args.to_version}: candidates", file=sys.stderr)
            renamed_fields = kept
            before = len(removed_fields)
            removed_fields = [r for r in removed_fields if r[1] not in target.get(r[0], ())]
            removed_models = [r for r in removed_models if r[0] not in target]
            print(f"{before - len(removed_fields)} 'DEL' fields still defined in "
                  f"{args.to_version}: skipped", file=sys.stderr)
    if args.sources or (not renamed_fields and not removed_fields):
        # No OpenUpgrade analysis for this version (or --sources: OpenUpgrade
        # does not see Enterprise nor the fields without data migration):
        # compare the sources
        repos = [pathlib.Path(spec.partition("@")[0]) for spec in args.repo]
        src_removed, candidates = ef.source_changes(
            repos,
            lambda repo: resolve_ref(repo, args.from_version),
            lambda repo: resolve_ref(repo, args.to_version),
            models_filter,
        )
        # "rename X to Y" in the commit message: confirmed
        confirmed, candidates = ef.promote_candidates(candidates)
        # oldname='x' on a field of the target (Odoo <= 12.0): confirmed
        confirmed = ef.oldname_renames(
            repos,
            lambda repo: resolve_ref(repo, args.from_version),
            lambda repo: resolve_ref(repo, args.to_version),
            models_filter,
        ) + confirmed
        renamed_fields, removed_fields, candidates = ef.merge_changes(
            (renamed_fields, removed_fields), (confirmed, src_removed, candidates)
        )

    candidates = ou_candidates + candidates
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


def extract_models(args):
    """Removed models and rename candidates by comparing the ``_name`` of the
    sources (for the versions OpenUpgrade does not cover yet)."""
    import extract_fields as ef

    step = step_name(args.from_version, args.to_version)
    out = pathlib.Path(args.output_dir)
    prefixes = tuple(args.models.split(",")) if args.models else None
    repos = [pathlib.Path(spec.partition("@")[0]) for spec in args.repo]
    removed, candidates = ef.model_changes(
        repos,
        lambda repo: resolve_ref(repo, args.from_version),
        lambda repo: resolve_ref(repo, args.to_version),
        (lambda model: model.startswith(prefixes)) if prefixes else (lambda model: True),
    )
    header = [
        f"Generated by tools/extract_changes.py models --from {args.from_version} --to {args.to_version}",
        f"Repositories: {', '.join(r.name for r in repos)}",
        "Do not edit: write corrections in curated.yaml (same folder, loaded first).",
    ]
    _write_rules(
        out / "removed_models" / step / "generated.yaml",
        header + ["Format: [model, source]"],
        removed,
        lambda r: f"- [{_q(r[0])}, {_q(r[1])}]",
    )
    _write_rules(
        out / "renamed_models" / step / "candidates.yaml",
        header + [
            "Rename CANDIDATES (the commit removing the model creates one model with",
            "half of its fields at least): check them, then copy to curated.yaml.",
        ],
        candidates,
        lambda r: f"# - [{_q(r[0])}, {_q(r[1])}, {_q(r[2])}]",
    )


def _yaml_sq(value):
    """YAML single quoted scalar."""
    return "'" + str(value).replace("'", "''") + "'"


def _write_text_rules(path, header, sections):
    """sections: {extension: [(comment, regex, value)]} in the format of
    text_errors / text_replaces."""
    path = pathlib.Path(path)
    count = sum(len(rows) for rows in sections.values())
    if not count:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {line}" for line in header]
    for extension, rows in sections.items():
        if not rows:
            continue
        lines.append(f"{extension}:")
        for comment, regex, value in rows:
            lines.append(f"  # {comment}")
            lines.append(f"  {_yaml_sq(regex)}: {_yaml_sq(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{count} rules written to {path}", file=sys.stderr)


def _step(args):
    return step_name(args.from_version, args.to_version)


def extract_js(args):
    import extract_assets as ea

    repos = [pathlib.Path(spec.partition("@")[0]) for spec in args.repo]
    moved, removed = ea.js_changes(
        repos,
        lambda repo: resolve_ref(repo, args.from_version),
        lambda repo: resolve_ref(repo, args.to_version),
    )
    out = pathlib.Path(args.output_dir)
    header = [
        f"Generated by tools/extract_changes.py js --from {args.from_version} --to {args.to_version}",
        "Do not edit: write corrections in another file of this folder.",
    ]
    tag = args.to_version.split(".")[0]

    def asset_path(name):
        # "@web/core/l10n/dates" -> "web/static/src/core/l10n/dates.js" (manifest assets)
        module, _, rest = name[1:].partition("/")
        return f"{module}/static/src/{rest}.js"

    replaces = {".js": [], ".py": []}
    errors = {".js": [], ".py": []}
    for old, new, source in moved:
        if old.split("/", 1)[0] != new.split("/", 1)[0]:
            # moved to another module: the importing module may not depend on it
            message = f"[{tag}] JS module {old} moved to {new} (another module: check the depends)"
            errors[".js"].append((source, rf"[\"']{re.escape(old)}[\"']", message))
            errors[".py"].append((source, rf"[\"']{re.escape(asset_path(old))}[\"']", message))
            continue
        replaces[".js"].append((source, rf"([\"']){re.escape(old)}\1", rf"\g<1>{new}\g<1>"))
        replaces[".py"].append((source, rf"([\"']){re.escape(asset_path(old))}\1",
                                rf"\g<1>{asset_path(new)}\g<1>"))
    for old, hint, source in removed:
        message = f"[{tag}] JS module {old} was removed" + (f" (moved to {hint}?)" if hint else "")
        errors[".js"].append((source, rf"[\"']{re.escape(old)}[\"']", message))
        errors[".py"].append((source, rf"[\"']{re.escape(asset_path(old))}[\"']", message))
    _write_text_rules(
        out / "text_replaces" / _step(args) / "js_modules.yaml",
        header + ["JS modules moved inside their module: same file name and same exports in the new place."],
        replaces,
    )
    _write_text_rules(
        out / "text_errors" / _step(args) / "js_modules.yaml",
        header + ["JS modules removed (imports and manifest assets)."],
        errors,
    )


def extract_views(args):
    import extract_assets as ea

    repos = [pathlib.Path(spec.partition("@")[0]) for spec in args.repo]
    removed = ea.view_changes(
        repos,
        lambda repo: resolve_ref(repo, args.from_version),
        lambda repo: resolve_ref(repo, args.to_version),
    )
    tag = args.to_version.split(".")[0]
    errors = {".xml": [], ".py": []}
    for xmlid, source in removed:
        message = f"[{tag}] View {xmlid} was removed or renamed: update the inherit_id / ref / t-call"
        quoted = rf"[\"']{re.escape(xmlid)}[\"']"
        errors[".xml"].append((source, rf"\b(?:ref|inherit_id|t-call)\s*=\s*{quoted}", message))
        errors[".py"].append((source, rf"\.ref\(\s*{quoted}", message))
    _write_text_rules(
        pathlib.Path(args.output_dir) / "text_errors" / _step(args) / "views.yaml",
        [
            f"Generated by tools/extract_changes.py views --from {args.from_version} --to {args.to_version}",
            f"Repositories: {', '.join(r.name for r in repos)}",
            "Views (ir.ui.view / template) removed from modules that still exist.",
            "Do not edit: write corrections in another file of this folder.",
        ],
        errors,
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


# odoo: addons/<module>/..., odoo/addons/<module>/... ; enterprise: <module>/...
MODULE_PATH_RE = re.compile(r"^(?:odoo/addons/|addons/)?(?P<module>\w+)/.*\.py$")
CLASS_RE = re.compile(r"^class \w+\(.*?\):\n(?P<body>(?:(?:[ \t]+.*|)\n)*)", re.M)
NAME_RE = re.compile(r"^[ \t]+_name\s*=\s*['\"]([\w.]+)['\"]", re.M)
INHERIT_RE = re.compile(r"^[ \t]+_inherit\s*=\s*(.+)$", re.M)


def extract_model_modules(args):
    """{model: module defining it} (for xmlids model_<model>): a class with
    _name and without the same name in _inherit. Ambiguous models are left out."""
    import extract_fields as ef

    owners = collections.defaultdict(set)
    for spec in args.repo:
        repo = pathlib.Path(spec)
        files = ef.read_blobs(repo, resolve_ref(repo, args.to_version), re.compile(r"\.py$"))
        for path, text in files.items():
            match = MODULE_PATH_RE.match(path)
            if not match or "/tests/" in path or path.startswith("odoo/addons/test_"):
                continue
            module = "base" if path.startswith("odoo/addons/base/") else match["module"]
            if path.startswith("odoo/") and module != "base":
                continue
            for cls in CLASS_RE.finditer(text):
                body = cls["body"]
                for name in NAME_RE.findall(body):
                    inherit = INHERIT_RE.search(body)
                    if inherit and re.search(r"['\"]%s['\"]" % re.escape(name), inherit[1]):
                        continue
                    owners[name].add(module)
    rows = sorted((m, mods.pop()) for m, mods in owners.items() if len(mods) == 1)
    lines = [
        f"# Module defining each model in {args.to_version} (xmlid <module>.model_<model>).",
        f"# Generated by tools/extract_changes.py model-modules --to {args.to_version}: do not edit.",
    ] + [f"{_q(m)}: {_q(mod)}" for m, mod in rows]
    pathlib.Path(args.output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(rows)} models written to {args.output}", file=sys.stderr)


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
    flds.add_argument("--sources", action="store_true",
                      help="compare the sources even when OpenUpgrade has data, and merge")
    flds.add_argument("--models", help="comma separated model prefixes (default: main apps)")
    flds.add_argument("--output-dir", required=True, help="odoo_module_migrate/migration_scripts")
    mdls = sub.add_parser("models", help="removed / renamed models (_name compared in the sources)")
    mdls.add_argument("--from", dest="from_version", required=True)
    mdls.add_argument("--to", dest="to_version", required=True)
    mdls.add_argument("--repo", action="append", required=True, help="bare repository, repeatable")
    mdls.add_argument("--models", help="comma separated model prefixes (default: all)")
    mdls.add_argument("--output-dir", required=True, help="odoo_module_migrate/migration_scripts")
    for name, help_text in (("js", "JS modules removed / moved"), ("views", "views (xmlid) removed")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--from", dest="from_version", required=True)
        cmd.add_argument("--to", dest="to_version", required=True)
        cmd.add_argument("--repo", action="append", required=True, help="bare repository, repeatable")
        cmd.add_argument("--output-dir", required=True, help="odoo_module_migrate/migration_scripts")
    for cmd in (flds, mdls, *[sub.choices[n] for n in ("js", "views")]):
        cmd.add_argument("--history-ref", help="branch whose full history is local (e.g. 17.0): commit searches limited to its lineage")
    mods = sub.add_parser("modules", help="removed / renamed / merged modules")
    mods.add_argument("--from", dest="from_version", required=True)
    mods.add_argument("--to", dest="to_version", required=True)
    mods.add_argument("--repo", action="append", required=True,
                      help="bare repository[@addons_prefix], repeatable")
    mods.add_argument("--openupgrade", help="OpenUpgrade clone (for apriori.py)")
    mods.add_argument("--output", help="YAML file (default: stdout)")
    mods.add_argument("--curated", help="hand-written rules to skip (default: curated.yaml next to --output)")
    mm = sub.add_parser("model-modules", help="module defining each model (for model_* xmlids)")
    mm.add_argument("--to", dest="to_version", required=True)
    mm.add_argument("--repo", action="append", required=True, help="bare repository, repeatable")
    mm.add_argument("--output", required=True)
    sub.add_parser("tools-exports", add_help=False,
                   help="names that 'from odoo.tools import X' cannot import anymore"
                        " (options: see extract_tools_exports.py --help)")
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["tools-exports"]:
        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        import extract_tools_exports

        return extract_tools_exports.main(argv[1:])
    args = parser.parse_args(argv)
    if args.command == "modules":
        if args.output and not args.curated:
            args.curated = str(pathlib.Path(args.output).with_name("curated.yaml"))
        extract_modules(args)
    else:
        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        if getattr(args, "history_ref", None):
            import extract_fields as ef

            ef.HISTORY_REF = args.history_ref
        {
            "fields": extract_fields, "api": extract_api, "models": extract_models,
            "js": extract_js, "views": extract_views, "model-modules": extract_model_modules,
        }[args.command](args)


if __name__ == "__main__":
    main()
