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
FIELD_RE = re.compile(r"^\s{4}(\w+)\s*=\s*fields\.(\w+)\(")
ANALYSIS_RE = re.compile(
    r"^(?P<module>\w+)\s*/\s*(?P<model>[\w.]+)\s*/\s*(?P<field>\w+)\s*\((?P<type>\w+)\)\s*:\s*DEL\b(?P<rest>.*)$"
)
OBSOLETE_MODEL_RE = re.compile(r"^obsolete model (?P<model>[\w.]+)")


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


def parse_fields(files):
    """{model: {field: (type, path)}} from Python sources (regex, best effort)."""
    result = collections.defaultdict(dict)
    for path, text in files.items():
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
    return result


def source_changes(repos, ref_from_of, ref_to_of, models_filter):
    """Removed fields and rename candidates by comparing the sources."""
    path_re = re.compile(r"/(models|wizards?|report)/[^/]+\.py$")
    removed, candidates = [], []
    for repo in repos:
        before = parse_fields(read_blobs(repo, ref_from_of(repo), path_re))
        after = parse_fields(read_blobs(repo, ref_to_of(repo), path_re))
        for model, fields in sorted(before.items()):
            if not models_filter(model) or model not in after:
                continue
            new_fields = {
                name: info for name, info in after[model].items() if name not in fields
            }
            for name, (ftype, path) in sorted(fields.items()):
                if name in after[model] or name.startswith("_"):
                    continue
                commit = _git(
                    repo, "log", "-1", "--format=%h%x09%s", f"-S{name} = fields.",
                    f"{ref_from_of(repo)}..{ref_to_of(repo)}", "--", path,
                ).decode("utf-8", "replace").strip()
                sha, _, subject = commit.partition("\t")
                source = f"{repo.name.removesuffix('.git')} {sha} {subject!r}" if sha else path
                same_type = [n for n, (t, _p) in new_fields.items() if t == ftype]
                added_in_commit = []
                if sha and same_type:
                    diff = _git(repo, "show", "--format=", sha, "--", path).decode("utf-8", "replace")
                    added_in_commit = [
                        n for n in same_type
                        if re.search(rf"^\+\s+{re.escape(n)}\s*=\s*fields\.", diff, re.M)
                    ]
                if len(added_in_commit) == 1:
                    candidates.append((model, name, added_in_commit[0], source))
                else:
                    removed.append((model, name, source))
    return removed, candidates


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
    return renamed_fields, renamed_models, removed_fields, removed_models


def dedupe(rows, key):
    seen, result = set(), []
    for row in rows:
        k = key(row)
        if k not in seen:
            seen.add(k)
            result.append(row)
    return result
