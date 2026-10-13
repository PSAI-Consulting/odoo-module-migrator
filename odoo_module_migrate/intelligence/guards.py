# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Structural guard of the edits a model may apply without a human.

Automatic application is limited to *symbol rewrites*: the parsed structure of
the file is identical before and after the edit, and every changed leaf is an
identifier or a dotted name (field, model, method, module, XML id) replaced by
another one. A statement, an element, a CSV row or a manifest key added or
removed, a number, a boolean or free text changed: all of these may alter
business behaviour, so they stay recommendations for a human.

Two operation types have an explicit, narrower allowance:

* ``add_import`` / ``replace_import``: only top-level import statements may
  change; every other statement must be strictly identical;
* manifests: only the ``depends`` list may change, by renaming or adding
  module names.

The guard also returns the symbols the edit removes and introduces, so the
evidence of the edit can be checked against them.
"""

from __future__ import annotations

import ast
import csv
import io
import re
from dataclasses import dataclass, field

from lxml import etree

SYMBOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*|\S")
MAX_CHANGED_SYMBOLS = 8
IMPORT_OPS = {"add_import", "replace_import"}
_MANIFEST_NAMES = {"__manifest__.py", "__openerp__.py"}


@dataclass
class GuardResult:
    ok: bool
    reason: str = ""
    renamed: list[tuple[str, str]] = field(default_factory=list)
    added: list[str] = field(default_factory=list)

    @property
    def introduced(self) -> set[str]:
        return {new for _old, new in self.renamed} | set(self.added)

    @property
    def removed(self) -> set[str]:
        return {old for old, _new in self.renamed}


def _fail(reason: str) -> GuardResult:
    return GuardResult(False, reason)


def _symbol_change(old: str, new: str, changes: list[tuple[str, str]], where: str) -> str:
    """Record a symbol-level change of a value; return an error or ''."""
    old_tokens = _TOKEN_RE.findall(old)
    new_tokens = _TOKEN_RE.findall(new)
    if len(old_tokens) != len(new_tokens):
        return f"{where} : structure de la valeur modifiée ({old!r} -> {new!r})"
    for a, b in zip(old_tokens, new_tokens):
        if a == b:
            continue
        if not (SYMBOL_RE.match(a) and SYMBOL_RE.match(b)):
            return f"{where} : seul un symbole peut être renommé ({a!r} -> {b!r})"
        if a.isdigit() or b.isdigit():
            return f"{where} : valeur numérique modifiée ({a!r} -> {b!r})"
        changes.append((a, b))
    return ""


# ---------------------------------------------------------------- Python

def _compare_ast(a, b, changes, path="module") -> str:
    if type(a) is not type(b):
        return f"{path} : nœud {type(a).__name__} remplacé par {type(b).__name__}"
    if isinstance(a, ast.AST):
        for name in a._fields:
            error = _compare_ast(getattr(a, name, None), getattr(b, name, None), changes, f"{path}.{name}")
            if error:
                return error
        return ""
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path} : {len(a)} élément(s) devenu(s) {len(b)} (instruction ajoutée ou supprimée)"
        for index, (x, y) in enumerate(zip(a, b)):
            error = _compare_ast(x, y, changes, f"{path}[{index}]")
            if error:
                return error
        return ""
    if a == b:
        return ""
    if isinstance(a, str) and isinstance(b, str) and SYMBOL_RE.match(a) and SYMBOL_RE.match(b):
        changes.append((a, b))
        return ""
    return f"{path} : valeur {a!r} -> {b!r} (seuls les symboles peuvent être renommés)"


def _imports(tree: ast.Module) -> set[tuple[int, str, str, str]]:
    result = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                result.add((node.level, node.module or "", alias.name, alias.asname or ""))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                result.add((0, "", alias.name, alias.asname or ""))
    return result


def _without_imports(tree: ast.Module) -> ast.Module:
    return ast.Module(
        body=[n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))],
        type_ignores=[],
    )


def _guard_python(before: str, after: str, op_type: str) -> GuardResult:
    try:
        old_tree, new_tree = ast.parse(before), ast.parse(after)
    except (SyntaxError, ValueError) as exc:
        return _fail(f"analyse Python impossible ({exc})")
    if op_type in IMPORT_OPS:
        if ast.dump(_without_imports(old_tree)) != ast.dump(_without_imports(new_tree)):
            return _fail("une opération d'import a modifié du code hors des imports")
        old_imports, new_imports = _imports(old_tree), _imports(new_tree)
        added = sorted(new_imports - old_imports)
        removed = sorted(old_imports - new_imports)
        if not added:
            return _fail("aucun import ajouté ni remplacé")
        if op_type == "add_import" and removed:
            return _fail("add_import a supprimé un import existant")
        removed_names = {(level, name, asname) for level, _module, name, asname in removed}
        renamed, plain_added = [], []
        for level, module, name, asname in added:
            symbol = f"{module}.{name}" if module else name
            previous = next(
                (f"{m}.{n}" if m else n for lv, m, n, a in removed if (lv, n, a) == (level, name, asname)),
                None,
            )
            if previous:
                renamed.append((previous, symbol))
            else:
                plain_added.append(symbol)
        if op_type == "replace_import" and not removed_names:
            return _fail("replace_import n'a remplacé aucun import")
        return GuardResult(True, renamed=renamed, added=plain_added)
    changes: list[tuple[str, str]] = []
    error = _compare_ast(old_tree, new_tree, changes)
    if error:
        return _fail(error)
    return _finish(changes)


def _guard_manifest(before: str, after: str) -> GuardResult:
    try:
        old, new = ast.literal_eval(before.lstrip()), ast.literal_eval(after.lstrip())
    except (SyntaxError, ValueError) as exc:
        return _fail(f"manifeste non littéral ({exc})")
    if not isinstance(old, dict) or not isinstance(new, dict):
        return _fail("manifeste qui n'est pas un dictionnaire")
    if set(old) != set(new) or any(old[k] != new[k] for k in old if k != "depends"):
        return _fail("seule la clé depends du manifeste peut être modifiée automatiquement")
    old_deps, new_deps = list(old.get("depends", [])), list(new.get("depends", []))
    if not all(isinstance(d, str) and SYMBOL_RE.match(d) for d in new_deps):
        return _fail("dépendance non symbolique")
    removed = [d for d in old_deps if d not in new_deps]
    added = [d for d in new_deps if d not in old_deps]
    if len(removed) > len(added) or len(set(new_deps)) != len(new_deps):
        return _fail("une dépendance a été supprimée ou dupliquée")
    renamed = list(zip(removed, added[: len(removed)]))
    return _finish(renamed, added[len(removed):])


# ---------------------------------------------------------------- XML

def _compare_xml(a, b, changes, path) -> str:
    if a.tag != b.tag:
        return f"{path} : balise {a.tag!r} remplacée par {b.tag!r}"
    if callable(a.tag):  # comment / processing instruction: text must not move
        if (a.text or "") != (b.text or ""):
            return f"{path} : commentaire modifié"
    else:
        if list(a.attrib) != list(b.attrib):
            return f"{path} : attributs ajoutés, supprimés ou réordonnés"
        for key in a.attrib:
            if a.attrib[key] != b.attrib[key]:
                error = _symbol_change(a.attrib[key], b.attrib[key], changes, f"{path}/@{key}")
                if error:
                    return error
    for kind in ("text", "tail"):
        old_text = " ".join((getattr(a, kind) or "").split())
        new_text = " ".join((getattr(b, kind) or "").split())
        if old_text != new_text:
            error = _symbol_change(old_text, new_text, changes, f"{path} ({kind})")
            if error:
                return error
    if len(a) != len(b):
        return f"{path} : élément ajouté ou supprimé"
    for index, (x, y) in enumerate(zip(a, b)):
        error = _compare_xml(x, y, changes, f"{path}/{x.tag if isinstance(x.tag, str) else 'comment'}[{index}]")
        if error:
            return error
    return ""


def _guard_xml(before: str, after: str) -> GuardResult:
    parser = etree.XMLParser(recover=False, remove_comments=False, resolve_entities=False)
    try:
        old = etree.fromstring(before.encode("utf-8"), parser=parser)
        new = etree.fromstring(after.encode("utf-8"), parser=parser)
    except etree.XMLSyntaxError as exc:
        return _fail(f"XML invalide ({exc})")
    changes: list[tuple[str, str]] = []
    error = _compare_xml(old, new, changes, old.tag if isinstance(old.tag, str) else "root")
    if error:
        return _fail(error)
    return _finish(changes)


# ---------------------------------------------------------------- CSV

def _guard_csv(before: str, after: str) -> GuardResult:
    try:
        old_rows = list(csv.reader(io.StringIO(before)))
        new_rows = list(csv.reader(io.StringIO(after)))
    except csv.Error as exc:
        return _fail(f"CSV invalide ({exc})")
    if len(old_rows) != len(new_rows):
        return _fail("ligne CSV ajoutée ou supprimée")
    changes: list[tuple[str, str]] = []
    for row_index, (old, new) in enumerate(zip(old_rows, new_rows)):
        if len(old) != len(new):
            return _fail(f"ligne CSV {row_index + 1} : nombre de colonnes modifié")
        if row_index == 0 and old != new:
            return _fail("en-tête CSV modifié")
        for column, (a, b) in enumerate(zip(old, new)):
            if a != b:
                error = _symbol_change(a, b, changes, f"CSV ligne {row_index + 1} colonne {column + 1}")
                if error:
                    return _fail(error)
    return _finish(changes)


def _finish(renamed, added=()) -> GuardResult:
    if not renamed and not added:
        return _fail("aucun symbole modifié : l'édition ne change que la mise en forme")
    if len(renamed) + len(added) > MAX_CHANGED_SYMBOLS:
        return _fail(f"{len(renamed) + len(added)} symboles modifiés (maximum {MAX_CHANGED_SYMBOLS})")
    return GuardResult(True, renamed=list(renamed), added=list(added))


def check_symbol_rewrite(rel_path: str, before: str, after: str, op_type: str = "") -> GuardResult:
    """Return whether ``before -> after`` is a pure symbol rewrite."""
    name = rel_path.replace("\\", "/").rsplit("/", 1)[-1]
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if name in _MANIFEST_NAMES:
        return _guard_manifest(before, after)
    if suffix == ".py":
        return _guard_python(before, after, op_type)
    if suffix == ".xml":
        return _guard_xml(before, after)
    if suffix == ".csv":
        return _guard_csv(before, after)
    return _fail(f"type de fichier {suffix or name!r} non vérifiable : application automatique interdite")
