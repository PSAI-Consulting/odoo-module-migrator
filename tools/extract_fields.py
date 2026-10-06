# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Field / model changes between two Odoo versions (used by extract_changes.py).

Two sources, in this order of trust:

1. OpenUpgrade (18.0, 19.0...): ``_renamed_fields`` / ``_renamed_models`` of
   the pre-migration.py scripts (they drive real data migrations) and the
   "DEL" lines of upgrade_analysis.txt;
2. the Odoo sources themselves (any version, e.g. 20.0 before OpenUpgrade):
   field definitions are compared between the two branches; a field deleted in
   the commit that adds a field of the same type on the same model is a
   *rename candidate*, written commented out (to be checked by hand).
"""

import ast
import collections
import re
import subprocess

CLASS_RE = re.compile(r"^class\s+\w+\s*\(([^)]*)\)\s*:")
NAME_RE = re.compile(r"^\s{4}_name\s*=\s*['\"]([\w.]+)['\"]")
INHERIT_RE = re.compile(r"^\s{4}_inherit\s*=\s*(?:\[\s*)?['\"]([\w.]+)['\"]")
FIELD_RE = re.compile(r"^\s{4}(\w+)\s*(?::[^=\n]+)?=\s*fields\.(\w+)\(")
ANALYSIS_RE = re.compile(
    r"^(?P<module>\w+)\s*/\s*(?P<model>[\w.]+)\s*/\s*(?P<field>\w+)\s*\((?P<type>\w+)\)\s*:\s*DEL\b(?P<rest>.*)$"
)
OBSOLETE_MODEL_RE = re.compile(r"^obsolete model (?P<model>[\w.]+)")


# Branch whose full history (with file contents) is available locally, e.g.
# 17.0 for the 8.0 -> 17.0 steps: commit searches are then limited to its
# lineage (merge-base(from, to)..merge-base(to, HISTORY_REF)), where field
# and model removals happen (master), instead of the stable forward-ports
# whose contents a partial clone would fetch one by one.
HISTORY_REF = None
_RANGES = {}


def log_range(repo, ref_from, ref_to):
    """Commit range searched for the changes between two branches."""
    if not HISTORY_REF:
        return f"{ref_from}..{ref_to}"
    key = (str(repo), ref_from, ref_to)
    if key not in _RANGES:
        base = _git(repo, "merge-base", ref_from, ref_to).decode().strip()
        top = _git(repo, "merge-base", ref_to, HISTORY_REF).decode().strip()
        _RANGES[key] = f"{base}..{top}"
    return _RANGES[key]


def _git(repo, *args, data=None):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], input=data, capture_output=True, check=True
    )
    return result.stdout


def read_blobs(repo, ref, path_re):
    """{path: text} of the files of `ref` whose path matches `path_re`."""
    listing = _git(repo, "ls-tree", "-r", ref).decode("utf-8", "replace")
    entries = []
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        if path_re.search(path):
            entries.append((meta.split()[2], path))
    if not entries:
        return {}
    out = _git(repo, "cat-file", "--batch", data="\n".join(sha for sha, _ in entries).encode() + b"\n")
    result, pos = {}, 0
    for sha, path in entries:
        header_end = out.index(b"\n", pos)
        size = int(out[pos:header_end].split()[2])
        start = header_end + 1
        result[path] = out[start:start + size].decode("utf-8", "replace")
        pos = start + size + 1
    return result


def _str_values(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _parse_ast(tree, path, result):
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        name, inherit, fields = None, [], {}
        for stmt in cls.body:
            # Odoo 20 annotates fields: country_id: ResCountry = fields.Many2one(...)
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value:
                target = stmt.target.id
            elif (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)):
                target = stmt.targets[0].id
            else:
                continue
            if target == "_name":
                name = (_str_values(stmt.value) or [None])[0]
            elif target == "_inherit":
                inherit = _str_values(stmt.value)
            elif (
                isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Attribute)
                and isinstance(stmt.value.func.value, ast.Name) and stmt.value.func.value.id == "fields"
            ):
                fields[target] = (stmt.value.func.attr, path)
        # a class with _inherit = [a, b] and no _name adds its fields to a and b
        for model in ([name] if name else inherit):
            result[model].update(fields)


def _parse_regex(text, path, result):
    model = None
    for line in text.splitlines():
        if CLASS_RE.match(line):
            model = None
            continue
        match = NAME_RE.match(line)
        if match:
            model = match[1]
            continue
        match = INHERIT_RE.match(line)
        if match and model is None:
            model = match[1]
            continue
        match = FIELD_RE.match(line)
        if match and model:
            result[model][match[1]] = (match[2], path)


CLASS_ATTR_RE = re.compile(
    r"^\s{4}(?P<attr>_name|_inherit|_inherits)\s*(?::[^=\n]+)?=\s*(?P<value>\{[^}]*\}|\[[^\]]*\]|\([^)]*\)|['\"][\w.]+['\"])",
    re.M,
)


def _regex_classes(text):
    """[(name, inherit)] of the classes of a file that ast cannot parse."""
    result = []
    for chunk in re.split(r"^class\s+\w+", text, flags=re.M)[1:]:
        name, inherit = None, []
        for match in CLASS_ATTR_RE.finditer(chunk):
            values = re.findall(r"['\"]([\w.]+)['\"]", match["value"])
            if match["attr"] == "_name":
                name = values[0] if values else None
            elif match["attr"] == "_inherits":
                inherit += values[0::2]  # keys of {"model": "field_id"}
            else:
                inherit += values
        result.append((name, inherit))
    return result


def parse_fields(files):
    """{model: {field: (type, path)}} from Python sources (ast; regex for the
    files the running Python cannot parse, e.g. newer syntax)."""
    result = collections.defaultdict(dict)
    for path, text in files.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            _parse_regex(text, path, result)
        else:
            _parse_ast(tree, path, result)
    return result


def model_parents(files):
    """{model: models it inherits from} (_inherit / _inherits of the classes)."""
    parents = collections.defaultdict(set)
    for text in files.values():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            for name, inherit in _regex_classes(text):
                model = name or (inherit[0] if inherit else None)
                if model:
                    parents[model].update(i for i in inherit if i != model)
            continue
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            name, inherit = None, []
            for stmt in cls.body:
                if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Name)):
                    continue
                if stmt.targets[0].id == "_name":
                    name = (_str_values(stmt.value) or [None])[0]
                elif stmt.targets[0].id == "_inherit":
                    inherit += _str_values(stmt.value)
                elif stmt.targets[0].id == "_inherits" and isinstance(stmt.value, ast.Dict):
                    inherit += [k.value for k in stmt.value.keys if isinstance(k, ast.Constant)]
            model = name or (inherit[0] if inherit else None)
            if model:
                parents[model].update(i for i in inherit if i != model)
    return parents


def available_fields(model, fields, parents):
    """Fields of `model`, including the ones of its parents / mixins."""
    result, todo, seen = set(fields.get(model, ())), [model], {model}
    while todo:
        for parent in parents.get(todo.pop(), ()):
            if parent not in seen:
                seen.add(parent)
                result |= set(fields.get(parent, ()))
                todo.append(parent)
    return result


def target_fields(repos, ref_of):
    """{model: field names} available on each model in `ref` (fields of its
    parent models and mixins included)."""
    files = {}
    for repo in repos:
        files.update(read_blobs(repo, ref_of(repo), re.compile(r"(^|/)(addons|models|wizards?|report)/.*\.py$")))
    fields, parents = parse_fields(files), model_parents(files)
    return {model: available_fields(model, fields, parents) for model in set(fields) | set(parents)}


ADDED_FIELD_RE = re.compile(r"^\+\s+(\w+)\s*=\s*fields\.", re.M)


def source_changes(repos, ref_from_of, ref_to_of, models_filter):
    """Removed fields and rename candidates by comparing the sources of all
    the repositories together (a field moved to enterprise is not removed)."""
    path_re = re.compile(r"(^|/)(addons|models|wizards?|report)/.*\.py$")
    before, after = collections.defaultdict(dict), collections.defaultdict(dict)
    after_files = {}
    for repo in repos:
        for model, fields in parse_fields(read_blobs(repo, ref_from_of(repo), path_re)).items():
            for name, (ftype, path) in fields.items():
                before[model][name] = (ftype, path, repo)
        files = read_blobs(repo, ref_to_of(repo), path_re)
        after_files.update(files)
        for model, fields in parse_fields(files).items():
            for name, (ftype, path) in fields.items():
                after[model][name] = (ftype, path, repo)
    # a field moved to a parent model / mixin still exists on the model
    parents = model_parents(after_files)
    added_fields = {}  # (repo, sha): field names added by the commit
    removed, candidates = [], []
    for model, fields in sorted(before.items()):
        if not models_filter(model) or model not in after:
            continue
        new_fields = {n: info for n, info in after[model].items() if n not in fields}
        still_there = available_fields(model, after, parents)
        for name, (ftype, path, repo) in sorted(fields.items()):
            if name in still_there or name.startswith("_"):
                continue
            commit = _git(
                repo, "log", "-1", "--format=%h%x09%s", f"-S{name} = fields.",
                log_range(repo, ref_from_of(repo), ref_to_of(repo)), "--", path,
            ).decode("utf-8", "replace").strip()
            sha, _, subject = commit.partition("\t")
            source = f"{repo.name.removesuffix('.git')} {sha} {subject!r}" if sha else path
            same_type = [n for n, info in new_fields.items() if info[0] == ftype]
            added_in_commit = []
            if sha and same_type:
                if (repo, sha) not in added_fields:
                    diff = _git(repo, "show", "--format=", sha).decode("utf-8", "replace")
                    added_fields[repo, sha] = set(ADDED_FIELD_RE.findall(diff))
                added_in_commit = [n for n in same_type if n in added_fields[repo, sha]]
            if len(added_in_commit) == 1:
                candidates.append((model, name, added_in_commit[0], source))
            else:
                removed.append((model, name, source))
    return removed, candidates


RENAME_SUBJECT_RE = re.compile(r"\brenam(?:e|ed|ing)\b", re.I)


def promote_candidates(candidates):
    """(confirmed, still candidates): a candidate is confirmed when the message
    of the commit says it is a rename and names the old field."""
    confirmed, rest = [], []
    for model, old, new, source in candidates:
        if RENAME_SUBJECT_RE.search(source) and re.search(rf"\b{re.escape(old)}\b", source):
            confirmed.append((model, old, new, source))
        else:
            rest.append((model, old, new, source))
    return confirmed, rest


def openupgrade_changes(openupgrade_git, ref, models_filter):
    """Renamed fields / models (pre-migration.py) and DEL fields (analysis)."""
    files = read_blobs(
        openupgrade_git, ref,
        re.compile(r"^openupgrade_scripts/scripts/[^/]+/[^/]+/(pre-migration\.py|upgrade_analysis\.txt)$"),
    )
    renamed_fields, renamed_models, removed_fields, removed_models = [], [], [], []
    for path, text in sorted(files.items()):
        source = f"OpenUpgrade {ref.split('/')[-1]} {path}"
        if path.endswith(".py"):
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in tree.body:
                if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
                    continue
                name = node.targets[0].id
                try:
                    value = ast.literal_eval(node.value)
                except ValueError:
                    continue
                if name.endswith("renamed_fields") or name.endswith("field_renames"):
                    for item in value:
                        if len(item) == 4:
                            renamed_fields.append((item[0], item[2], item[3], source))
                elif name.endswith("renamed_models") or name.endswith("model_renames"):
                    for item in value:
                        renamed_models.append((item[0], item[1], source))
        else:
            for line in text.splitlines():
                match = ANALYSIS_RE.match(line.strip())
                if match and models_filter(match["model"]):
                    removed_fields.append((match["model"], match["field"], source))
                match = OBSOLETE_MODEL_RE.match(line.strip())
                if match:
                    removed_models.append((match["model"], source))
    renamed_keys = {(m, old) for m, old, _new, _s in renamed_fields}
    removed_fields = [r for r in removed_fields if (r[0], r[1]) not in renamed_keys]
    # a renamed model is "obsolete" under its old name in the analysis
    renamed_model_names = {old for old, _new, _s in renamed_models}
    removed_models = [r for r in removed_models if r[0] not in renamed_model_names]
    return renamed_fields, renamed_models, removed_fields, removed_models


MODEL_PATH_RE = re.compile(r"(^|/)(addons|models|wizards?|report)/.*\.py$")


def defined_models(files):
    """{model: path} of the models created (``_name`` different from every
    ``_inherit``) in the Python sources."""
    result = {}
    for path, text in sorted(files.items()):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            # newer syntax than the running Python (e.g. Odoo 20 with 3.11)
            for name, inherit in _regex_classes(text):
                if name and name not in inherit:
                    result.setdefault(name, path)
            continue
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            name, inherit = None, []
            for stmt in cls.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value:
                    target = stmt.target.id
                elif (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Name)):
                    target = stmt.targets[0].id
                else:
                    continue
                if target == "_name":
                    name = (_str_values(stmt.value) or [None])[0]
                elif target == "_inherit":
                    inherit = _str_values(stmt.value)
            if name and name not in inherit:
                result.setdefault(name, path)
    return result


ADDED_NAME_RE = re.compile(r"^\+\s+_name\s*(?::[^=\n]+)?=\s*['\"]([\w.]+)['\"]", re.M)


def model_changes(repos, ref_from_of, ref_to_of, models_filter=lambda m: True):
    """(removed, candidates) models between two branches of all the
    repositories together (a model moved to another module still exists).

    removed:    [(model, source)]
    candidates: [(old_model, new_model, source)]: the commit that deletes the
                model creates exactly one model having half of its fields at
                least (rename to check by hand)."""
    before, after = {}, {}
    fields_before, fields_after = collections.defaultdict(dict), collections.defaultdict(dict)
    where = {}
    for repo in repos:
        files = read_blobs(repo, ref_from_of(repo), MODEL_PATH_RE)
        for model, path in defined_models(files).items():
            before.setdefault(model, path)
            where.setdefault(model, repo)
        for model, flds in parse_fields(files).items():
            fields_before[model].update(flds)
        files = read_blobs(repo, ref_to_of(repo), MODEL_PATH_RE)
        for model, path in defined_models(files).items():
            after.setdefault(model, path)
        for model, flds in parse_fields(files).items():
            fields_after[model].update(flds)
    new_models = set(after) - set(before)
    created = {}  # (repo, sha): models whose _name is added by the commit
    removed, candidates = [], []
    for model in sorted(set(before) - set(after)):
        if not models_filter(model):
            continue
        repo, path = where[model], before[model]
        commit = ""
        try:
            commit = _git(
                repo, "log", "-1", "--format=%h%x09%s",
                rf"-G_name\s*(:[^=]+)?=\s*['\"]{re.escape(model)}['\"]",
                log_range(repo, ref_from_of(repo), ref_to_of(repo)), "--", path,
            ).decode("utf-8", "replace").strip()
        except subprocess.CalledProcessError:
            pass
        sha, _, subject = commit.partition("\t")
        source = f"{repo.name.removesuffix('.git')} {sha} {subject!r}" if sha else path
        added = []
        if sha:
            if (repo, sha) not in created:
                diff = _git(repo, "show", "--format=", sha).decode("utf-8", "replace")
                created[repo, sha] = set(ADDED_NAME_RE.findall(diff))
            old_fields = set(fields_before.get(model, ()))
            for new in sorted(new_models & created[repo, sha]):
                common = old_fields & set(fields_after.get(new, ()))
                if old_fields and len(common) * 2 >= len(old_fields):
                    added.append(new)
        if len(added) == 1:
            candidates.append((model, added[0], source))
        else:
            removed.append((model, source))
    return removed, candidates


def merge_changes(openupgrade, sources):
    """Merge (renamed, removed) of OpenUpgrade with (renamed, removed,
    candidates) of the sources, OpenUpgrade first, without duplicates.

    A field renamed by one source is neither removed nor a candidate; a
    candidate is not removed (it stays reported as candidate)."""
    ou_renamed, ou_removed = openupgrade
    src_renamed, src_removed, src_candidates = sources
    renamed = dedupe(list(ou_renamed) + list(src_renamed), lambda r: (r[0], r[1]))
    renamed_keys = {(r[0], r[1]) for r in renamed}
    candidates = dedupe(
        [c for c in src_candidates if (c[0], c[1]) not in renamed_keys], lambda r: (r[0], r[1])
    )
    skip = renamed_keys | {(c[0], c[1]) for c in candidates}
    removed = dedupe(
        [r for r in list(ou_removed) + list(src_removed) if (r[0], r[1]) not in skip],
        lambda r: (r[0], r[1]),
    )
    return renamed, removed, candidates


def dedupe(rows, key):
    seen, result = set(), []
    for row in rows:
        k = key(row)
        if k not in seen:
            seen.add(k)
            result.append(row)
    return result
