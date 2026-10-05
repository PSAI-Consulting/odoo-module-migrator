# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""JS modules and views changes between two Odoo versions (used by
extract_changes.py js / views).

JS: the ES modules ``addons/<module>/static/src/<path>.js`` are imported as
``@<module>/<path>``. A module present in N and absent in N+1 is:

* *moved* when exactly one new file of N+1 has the same file name and exports
  every name the old one exported: the import is rewritten (text_replaces);
* *removed* otherwise: the import is reported (text_errors), with the file of
  the same name when there is one ("moved to ...?").

Views: the ``ir.ui.view`` records and ``<template>`` of N whose xmlid is
absent from N+1, in modules present in both versions (a removed module is
reported by deprecated_modules). Their uses (``inherit_id``, ``ref``,
``t-call``, ``env.ref``) are reported (text_errors).
"""

import collections
import re
import subprocess

from extract_fields import _git, read_blobs

JS_PATH_RE = re.compile(r"(?:^|/)addons/(?P<module>\w+)/static/src/(?P<path>.+)\.js$")
EXPORT_RE = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?(?:class|function\*?|const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)",
    re.M,
)
EXPORT_LIST_RE = re.compile(r"^\s*export\s*\{(?P<names>[^}]*)\}", re.M)
EXPORT_DEFAULT_RE = re.compile(r"^\s*export\s+default\b", re.M)


def js_exports(text):
    """Names exported by an ES module ("default" for a default export)."""
    names = {m["name"] for m in EXPORT_RE.finditer(text)}
    for match in EXPORT_LIST_RE.finditer(text):
        for item in match["names"].split(","):
            item = item.strip()
            if item:
                names.add(item.split(" as ")[-1].strip())
    if EXPORT_DEFAULT_RE.search(text):
        names.add("default")
    return names


def _js_modules(files):
    """{"@module/path": (file path, text)}"""
    result = {}
    for path, text in files.items():
        match = JS_PATH_RE.search(path)
        if match:
            result[f"@{match['module']}/{match['path']}"] = (path, text)
    return result


def _last_commit(repo, ref_from, ref_to, path, regex=None):
    args = ["log", "-1", "--format=%h%x09%s"]
    if regex:
        args.append(f"-G{regex}")
    try:
        out = _git(repo, *args, f"{ref_from}..{ref_to}", "--", path).decode("utf-8", "replace").strip()
    except subprocess.CalledProcessError:
        return ""
    sha, _, subject = out.partition("\t")
    return f"{repo.name.removesuffix('.git')} {sha} {subject!r}" if sha else ""


def js_changes(repos, ref_from_of, ref_to_of):
    """(moved, removed):
    moved:   [(old_import, new_import, source)]
    removed: [(old_import, hint, source)]  hint: import of a file of the same name or ''"""
    moved, removed = [], []
    for repo in repos:
        ref_from, ref_to = ref_from_of(repo), ref_to_of(repo)
        before = _js_modules(read_blobs(repo, ref_from, JS_PATH_RE))
        after = _js_modules(read_blobs(repo, ref_to, JS_PATH_RE))
        by_name = collections.defaultdict(list)
        for name in set(after) - set(before):
            by_name[name.rsplit("/", 1)[-1]].append(name)
        for name in sorted(set(before) - set(after)):
            path, text = before[name]
            source = _last_commit(repo, ref_from, ref_to, path) or f"{repo.name.removesuffix('.git')} {path}"
            same = by_name.get(name.rsplit("/", 1)[-1], [])
            exports = js_exports(text)
            if len(same) == 1 and exports and exports <= js_exports(after[same[0]][1]):
                moved.append((name, same[0], source))
            else:
                removed.append((name, same[0] if len(same) == 1 else "", source))
    return moved, removed


MANIFEST_RE = re.compile(r"^(?:.*/)?addons/(?P<module>\w+)/__manifest__\.py$")
XML_RE = re.compile(r"(?:^|/)addons/(?P<module>\w+)/(?!static/|tests?/).*\.xml$")
RECORD_RE = re.compile(r"<record\b(?P<attrs>[^>]*)>", re.S)
TEMPLATE_RE = re.compile(r"<template\b(?P<attrs>[^>]*)>", re.S)
ATTR_RE = re.compile(r"""\b(?P<name>id|model)\s*=\s*(?P<q>["'])(?P<value>.*?)(?P=q)""", re.S)


def _xml_views(files):
    """{xmlid: path} of the views (ir.ui.view records and templates)."""
    result = {}
    for path, text in files.items():
        match = XML_RE.search(path)
        if not match:
            continue
        module = match["module"]
        for regex, needs_model in ((RECORD_RE, True), (TEMPLATE_RE, False)):
            for tag in regex.finditer(text):
                attrs = {a["name"]: a["value"] for a in ATTR_RE.finditer(tag["attrs"])}
                if not attrs.get("id") or (needs_model and attrs.get("model") != "ir.ui.view"):
                    continue
                xmlid = attrs["id"] if "." in attrs["id"] else f"{module}.{attrs['id']}"
                result.setdefault(xmlid, path)
    return result


def view_changes(repos, ref_from_of, ref_to_of):
    """[(xmlid, source)] of the views removed in modules present in both
    versions (all the repositories together)."""
    before, after, modules_before, modules_after, where = {}, {}, set(), set(), {}
    for repo in repos:
        ref_from, ref_to = ref_from_of(repo), ref_to_of(repo)
        files = read_blobs(repo, ref_from, re.compile(r"\.xml$|__manifest__\.py$"))
        modules_before |= {m["module"] for m in map(MANIFEST_RE.search, files) if m}
        for xmlid, path in _xml_views(files).items():
            before.setdefault(xmlid, path)
            where.setdefault(xmlid, (repo, ref_from, ref_to))
        files = read_blobs(repo, ref_to, re.compile(r"\.xml$|__manifest__\.py$"))
        modules_after |= {m["module"] for m in map(MANIFEST_RE.search, files) if m}
        after.update({x: p for x, p in _xml_views(files).items() if x not in after})
    removed = []
    for xmlid in sorted(set(before) - set(after)):
        module, _, name = xmlid.partition(".")
        if module not in modules_before & modules_after:
            continue
        repo, ref_from, ref_to = where[xmlid]
        path = before[xmlid]
        source = _last_commit(
            repo, ref_from, ref_to, path, rf"id=[\"']({re.escape(module)}\.)?{re.escape(name)}[\"']"
        ) or f"{repo.name.removesuffix('.git')} {path}"
        removed.append((xmlid, source))
    return removed
