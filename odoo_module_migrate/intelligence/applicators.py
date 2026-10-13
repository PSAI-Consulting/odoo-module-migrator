# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Deterministic typed applicators for model-proposed edits.

Every applicator:

1. parses the file and locates exactly one target (AST node, XML element,
   CSV cell, manifest list) — zero or several candidates is a rejection;
2. rewrites only the characters of that target, everything else is kept
   byte for byte (comments, quotes, line endings handled by the caller);
3. validates names it inserts (identifiers only: no code smuggled in a
   "name");
4. checks the syntax of the result and returns a unified diff.

They work on text whose line endings are normalised to ``\\n``
(:func:`odoo_module_migrate.tools._read_content`); the writer restores the
original encoding, BOM and line endings. JavaScript is never edited.
"""

from __future__ import annotations

import ast
import csv
import difflib
import io
import logging
import pathlib
import re
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from lxml import etree

from .. import tools

logger = logging.getLogger(__name__)

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DOTTED_RE = re.compile(r"^\.*[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$|^\.+$")
MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass
class ApplicatorResult:
    success: bool
    status: str
    error: str = ""
    diff: str = ""
    new_content: str = ""
    lines_changed: int = 0


def _reject(status: str, error: str = "") -> ApplicatorResult:
    return ApplicatorResult(False, f"rejected: {status}", error or status)


def generate_diff(old_text: str, new_text: str, filename: str) -> tuple[str, int]:
    """Unified diff and number of added + removed lines."""
    diff_lines = list(difflib.unified_diff(
        old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
        fromfile=f"a/{filename}", tofile=f"b/{filename}",
    ))
    changed = sum(1 for line in diff_lines if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
    return "".join(diff_lines), changed


def validate_syntax(path: pathlib.Path | str, content: str) -> tuple[bool, str]:
    """Strictly validate file syntax according to its extension."""
    suffix = pathlib.Path(path).suffix.lower()
    try:
        if suffix == ".py":
            ast.parse(content)
        elif suffix == ".xml":
            etree.fromstring(content.encode("utf-8"), parser=etree.XMLParser(recover=False, resolve_entities=False))
        elif suffix == ".csv":
            list(csv.reader(io.StringIO(content)))
        elif suffix == ".js":
            return False, "modification automatique JavaScript non supportée"
        else:
            return False, f"extension non validable ({suffix})"
    except (SyntaxError, ValueError, etree.XMLSyntaxError, csv.Error) as exc:
        return False, f"syntaxe invalide après édition: {exc}"
    return True, ""


def _done(file_path: pathlib.Path, old: str, new: str) -> ApplicatorResult:
    if old == new:
        return _reject("édition sans effet")
    valid, reason = validate_syntax(file_path, new)
    if not valid:
        return _reject(reason)
    diff, changed = generate_diff(old, new, file_path.name)
    return ApplicatorResult(True, "applied", diff=diff, new_content=new, lines_changed=changed)


def _content(file_path: pathlib.Path, current_content: str | None) -> str:
    return current_content if current_content is not None else tools._read_content(file_path)


def _line_offsets(text: str) -> list[int]:
    offsets, total = [0], 0
    for line in text.split("\n"):
        total += len(line) + 1
        offsets.append(total)
    return offsets


def _char_offset(text: str, offsets: list[int], lineno: int, byte_col: int) -> int:
    """ast positions are UTF-8 byte columns; convert to a str index."""
    start = offsets[lineno - 1]
    line = text[start:offsets[lineno] - 1] if lineno < len(offsets) else text[start:]
    return start + len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="strict"))


# ---------------------------------------------------------------- exact text

class ExactTextApplicator:
    """Replaces one exact, unique snippet (the structural guard decides the rest)."""

    @staticmethod
    def apply(
        file_path: pathlib.Path,
        old_text: str,
        new_text: str,
        current_content: str | None = None,
        max_chars: int = 8000,
    ) -> ApplicatorResult:
        if file_path.suffix.lower() == ".js":
            return _reject("JavaScript non validé", "JS auto-application forbidden")
        if not old_text:
            return _reject("texte attendu vide")
        if len(old_text) > max_chars or len(new_text) > max_chars:
            return _reject("édition trop volumineuse")
        content = _content(file_path, current_content)
        count = content.count(old_text)
        if count == 0:
            return _reject("texte attendu absent")
        if count > 1:
            return _reject("texte attendu non unique", f"snippet found {count} times")
        return _done(file_path, content, content.replace(old_text, new_text, 1))


# ---------------------------------------------------------------- Python imports

class PythonImportApplicator:
    """Replaces or adds one import statement located by the AST."""

    @staticmethod
    def replace_import(
        file_path: pathlib.Path,
        old_module: str,
        new_module: str,
        imported_name: str = "",
        current_content: str | None = None,
        target_line: int | None = None,
    ) -> ApplicatorResult:
        if not (DOTTED_RE.match(old_module or "") and DOTTED_RE.match(new_module or "")):
            return _reject("nom de module d'import invalide")
        if imported_name and not IDENTIFIER_RE.match(imported_name):
            return _reject("nom importé invalide")
        content = _content(file_path, current_content)
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return _reject(f"syntaxe initiale invalide ({exc})")

        candidates = []
        statements = [n for n in ast.walk(tree) if isinstance(n, ast.stmt)]
        for node in statements:
            if isinstance(node, ast.ImportFrom):
                full = "." * node.level + (node.module or "")
                if full == old_module and (not imported_name or any(a.name == imported_name for a in node.names)):
                    candidates.append(node)
            elif isinstance(node, ast.Import) and not imported_name:
                if any(a.name == old_module for a in node.names):
                    candidates.append(node)
        if target_line is not None:
            candidates = [n for n in candidates if n.lineno <= target_line <= n.end_lineno]
        if not candidates:
            return _reject("import attendu absent")
        if len(candidates) > 1:
            return _reject("import ambigu", f"{len(candidates)} matching imports")
        node = candidates[0]
        lines = content.split("\n")
        # The statement must own its lines: `import a; import b` is ambiguous.
        for other in statements:
            overlaps = not (other.end_lineno < node.lineno or other.lineno > node.end_lineno)
            encloses = (
                other.lineno <= node.lineno and other.end_lineno >= node.end_lineno
                and not isinstance(other, (ast.Import, ast.ImportFrom))
            )
            if other is not node and overlaps and not encloses:
                return _reject("plusieurs instructions sur la ligne de l'import")
        first = lines[node.lineno - 1]
        indent = first[: len(first) - len(first.lstrip())]
        if len(first.encode("utf-8")) - len(first.lstrip().encode("utf-8")) != node.col_offset:
            return _reject("import précédé d'une autre instruction sur la ligne")
        last = lines[node.end_lineno - 1]
        comment = ""
        code_end = len(last.encode("utf-8")[: node.end_col_offset].decode("utf-8"))
        tail = last[code_end:]
        if tail.strip():
            if not tail.lstrip().startswith("#"):
                return _reject("texte inattendu après l'import")
            comment = tail

        def render(alias: ast.alias, module: str) -> str:
            name = new_module if (isinstance(node, ast.Import) and alias.name == old_module) else alias.name
            return name if not alias.asname else f"{name} as {alias.asname}"

        if isinstance(node, ast.Import):
            new_lines = [f"{indent}import {', '.join(render(a, new_module) for a in node.names)}{comment}"]
        else:
            moved = [a for a in node.names if not imported_name or a.name == imported_name]
            kept = [a for a in node.names if a not in moved]
            new_lines = []
            if kept:
                new_lines.append(f"{indent}from {old_module} import {', '.join(render(a, old_module) for a in kept)}")
            new_lines.append(f"{indent}from {new_module} import {', '.join(render(a, new_module) for a in moved)}{comment}")
        new_content = "\n".join(lines[: node.lineno - 1] + new_lines + lines[node.end_lineno:])
        return _done(file_path, content, new_content)

    @staticmethod
    def add_import(
        file_path: pathlib.Path,
        module: str,
        name: str,
        current_content: str | None = None,
    ) -> ApplicatorResult:
        if not DOTTED_RE.match(module or "") or not IDENTIFIER_RE.match(name or ""):
            return _reject("module ou nom importé invalide")
        content = _content(file_path, current_content)
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return _reject(f"syntaxe invalide ({exc})")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and "." * node.level + (node.module or "") == module and any(
                (a.asname or a.name) == name for a in node.names
            ):
                return _reject("import déjà présent")
            if isinstance(node, (ast.Import, ast.ImportFrom)) and any((a.asname or a.name) == name for a in node.names):
                return _reject("nom déjà importé depuis un autre module")
        lines = content.split("\n")
        body = tree.body
        insert_after = 0  # number of lines kept above the new import
        index = 0
        if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            insert_after = body[0].end_lineno
            index = 1
        while index < len(body) and isinstance(body[index], (ast.Import, ast.ImportFrom)):
            insert_after = body[index].end_lineno
            index += 1
        if insert_after == 0:
            # keep shebang, encoding, licence header comments and blank lines on top
            while insert_after < len(lines) and (not lines[insert_after].strip() or lines[insert_after].lstrip().startswith("#")):
                insert_after += 1
            while insert_after > 0 and not lines[insert_after - 1].strip():
                insert_after -= 1
        new_lines = [*lines[:insert_after], f"from {module} import {name}", *lines[insert_after:]]
        return _done(file_path, content, "\n".join(new_lines))


# ---------------------------------------------------------------- dict keys

class PythonDictKeyApplicator:
    """Renames one string key of a dict literal, located by AST position."""

    @staticmethod
    def rename_key(
        file_path: pathlib.Path,
        old_key: str,
        new_key: str,
        current_content: str | None = None,
        target_line: int | None = None,
    ) -> ApplicatorResult:
        if not IDENTIFIER_RE.match(new_key or "") and not DOTTED_RE.match(new_key or ""):
            return _reject("nouvelle clé non symbolique")
        content = _content(file_path, current_content)
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return _reject(f"syntaxe invalide ({exc})")
        keys = [
            k for node in ast.walk(tree) if isinstance(node, ast.Dict)
            for k in node.keys if isinstance(k, ast.Constant) and k.value == old_key
        ]
        if target_line is not None:
            keys = [k for k in keys if k.lineno == target_line]
        if not keys:
            return _reject("clé absente des dictionnaires")
        if len(keys) > 1:
            return _reject("clé présente dans plusieurs dictionnaires",
                           f"{len(keys)} candidates; give the line of the key")
        key = keys[0]
        if key.lineno != key.end_lineno:
            return _reject("clé sur plusieurs lignes")
        offsets = _line_offsets(content)
        start = _char_offset(content, offsets, key.lineno, key.col_offset)
        end = _char_offset(content, offsets, key.end_lineno, key.end_col_offset)
        literal = content[start:end]
        match = re.fullmatch(r"(?P<q>['\"])(?P<body>[^'\"\\\n]*)(?P=q)", literal)
        if not match or match.group("body") != old_key:
            return _reject("littéral de clé non simple (préfixe, échappement ou concaténation)")
        quote = match.group("q")
        return _done(file_path, content, content[:start] + f"{quote}{new_key}{quote}" + content[end:])


# ---------------------------------------------------------------- XML

_XML_SKIP_RE = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<!DOCTYPE[^>]*>", re.DOTALL)


def _start_tags(content: str, tag: str) -> list[tuple[int, int]]:
    """Spans of the ``<tag ...>`` start tags outside comments / CDATA / PIs,
    in document order (the order of ``etree.iter(tag)``)."""
    masked = list(content)
    for match in _XML_SKIP_RE.finditer(content):
        for index in range(match.start(), match.end()):
            if masked[index] != "\n":
                masked[index] = " "
    text = "".join(masked)
    spans = []
    for match in re.finditer(rf"<{re.escape(tag)}(?=[\s/>])", text):
        quote, index = None, match.end()
        while index < len(text):
            char = text[index]
            if quote:
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char == ">":
                spans.append((match.start(), index + 1))
                break
            index += 1
    return spans


def _replace_attribute(content: str, span: tuple[int, int], attribute: str, old_value: str, new_value: str) -> str | None:
    tag_text = content[span[0]:span[1]]
    found = list(re.finditer(
        rf"""(?<![\w:.-]){re.escape(attribute)}\s*=\s*(?P<q>["'])(?P<v>.*?)(?P=q)""", tag_text, re.DOTALL
    ))
    if len(found) != 1:
        return None
    match = found[0]
    parsed = etree.fromstring(f"<a v={match.group('q')}{match.group('v')}{match.group('q')}/>".encode()).get("v")
    if parsed != old_value:
        return None
    quote = match.group("q")
    escaped = xml_escape(new_value, {quote: "&quot;" if quote == '"' else "&apos;"})
    start = span[0] + match.start("v")
    end = span[0] + match.end("v")
    return content[:start] + escaped + content[end:]


def _parse_xml(content: str):
    return etree.fromstring(content.encode("utf-8"), parser=etree.XMLParser(recover=False, resolve_entities=False))


class XmlAttributeApplicator:
    """Sets one attribute of exactly one element, located by lxml then by
    its own start tag (never by a nearby line)."""

    @staticmethod
    def set_attribute(
        file_path: pathlib.Path,
        element_tag: str,
        attribute_name: str,
        old_value: str,
        new_value: str,
        identifier: str = "",
        current_content: str | None = None,
    ) -> ApplicatorResult:
        if not re.fullmatch(r"[A-Za-z_][\w.-]*", element_tag or "") or not re.fullmatch(r"[A-Za-z_][\w.:-]*", attribute_name or ""):
            return _reject("balise ou attribut invalide")
        content = _content(file_path, current_content)
        try:
            root = _parse_xml(content)
        except etree.XMLSyntaxError as exc:
            return _reject(f"XML initial invalide ({exc})")
        elements = list(root.iter(element_tag))
        spans = _start_tags(content, element_tag)
        if len(elements) != len(spans):
            return _reject("éléments XML impossibles à localiser sans ambiguïté (espaces de noms ?)")
        matches = [
            index for index, el in enumerate(elements)
            if el.get(attribute_name) == old_value
            and (not identifier or identifier in {v for k, v in el.attrib.items() if k != attribute_name})
        ]
        if not matches:
            return _reject("élément XML introuvable")
        if len(matches) > 1:
            return _reject("élément XML non unique", f"{len(matches)} elements; give an identifier attribute value")
        new_content = _replace_attribute(content, spans[matches[0]], attribute_name, old_value, new_value)
        if new_content is None:
            return _reject("attribut introuvable dans la balise de l'élément")
        return _done(file_path, content, new_content)


class TargetViewTrees:
    """Target view archs, by XML id, supporting XPath queries.

    Given a :class:`~odoo_module_migrate.analysis.views.ViewIndex`, a view is
    queried through ``combined_parent``: its architecture as modified by its
    ancestors, which is what Odoo validates an inheriting view against.
    """

    def __init__(self, arches: Any = None):
        self.index = arches if hasattr(arches, "combined_parent") else None
        self._combined: dict[str, Any] = {}
        if self.index is not None:
            self.by_id = dict(self.index.arches)
        elif isinstance(arches, dict):
            self.by_id = {k: v for k, v in arches.items() if hasattr(v, "xpath")}
        elif isinstance(arches, (list, tuple, set)):
            self.by_id = {str(i): t for i, t in enumerate(arches) if hasattr(t, "xpath")}
        elif hasattr(arches, "xpath"):
            self.by_id = {"0": arches}
        else:
            self.by_id = {}

    @property
    def trees(self) -> list[Any]:
        return list(self.by_id.values())

    def _view(self, view: str) -> Any:
        if self.index is not None:
            if view not in self._combined:
                self._combined[view] = self.index.combined_parent(view)
            if self._combined[view] is not None:
                return self._combined[view]
        return self.by_id.get(view)

    def xpath(self, expr: str, view: str = "") -> list[Any]:
        if view:
            tree = self._view(view)
            trees = [tree] if tree is not None else []
        else:
            trees = self.trees
        results = []
        for tree in trees:
            try:
                found = tree.xpath(expr)
            except etree.XPathError as exc:
                logger.debug("XPath evaluation error on view tree: %s", exc)
                continue
            if isinstance(found, list):
                results.extend(found)
            elif found:
                results.append(found)
        return results

    def __bool__(self) -> bool:
        return bool(self.by_id)


def _inherited_view(element) -> str:
    """XML id of the view an <xpath> extends (record or template)."""
    for ancestor in element.iterancestors():
        if ancestor.tag == "record":
            ref = ancestor.find("field[@name='inherit_id']")
            return ref.get("ref", "") if ref is not None else ""
        if ancestor.tag == "template":
            return ancestor.get("inherit_id", "")
    return ""


class XmlXPathApplicator:
    """Replaces the ``expr`` of one ``<xpath>``; the new expression must be
    valid and, when the parent view is indexed, must match in it."""

    @staticmethod
    def replace_expr(
        file_path: pathlib.Path,
        old_expr: str,
        new_expr: str,
        current_content: str | None = None,
        target_view_tree: Any | None = None,
        require_anchor: bool = False,
        module_name: str = "",
    ) -> ApplicatorResult:
        content = _content(file_path, current_content)
        try:
            etree.XPath(new_expr)
        except etree.XPathSyntaxError as exc:
            return _reject(f"nouvelle expression XPath invalide ({exc})")
        try:
            root = _parse_xml(content)
        except etree.XMLSyntaxError as exc:
            return _reject(f"XML initial invalide ({exc})")
        elements = list(root.iter("xpath"))
        spans = _start_tags(content, "xpath")
        if len(elements) != len(spans):
            return _reject("balises xpath impossibles à localiser sans ambiguïté")
        matches = [i for i, el in enumerate(elements) if el.get("expr") == old_expr]
        if not matches:
            return _reject("xpath expr introuvable")
        if len(matches) > 1:
            return _reject("xpath expr non unique")
        element = elements[matches[0]]
        if require_anchor and not target_view_tree:
            return _reject("vues cibles absentes pour valider l'ancre XPath")
        if target_view_tree:
            view = _inherited_view(element)
            if view and "." not in view and module_name:
                view = f"{module_name}.{view}"
            known = view and view in getattr(target_view_tree, "by_id", {})
            if require_anchor and not known:
                return _reject(f"vue parente {view or '?'} non indexée : ancre invérifiable")
            if known and not target_view_tree.xpath(new_expr, view):
                return _reject(f"ancre XPath introuvable dans la vue parente {view}")
        new_content = _replace_attribute(content, spans[matches[0]], "expr", old_expr, new_expr)
        if new_content is None:
            return _reject("attribut expr introuvable dans la balise")
        return _done(file_path, content, new_content)


# ---------------------------------------------------------------- manifest

class ManifestDependencyApplicator:
    """Adds one dependency to the ``depends`` list located by the AST."""

    @staticmethod
    def add_dependency(
        file_path: pathlib.Path,
        dependency_name: str,
        current_content: str | None = None,
        known_modules: set[str] | None = None,
        dependency_graph: dict[str, list[str]] | None = None,
        module_name: str = "",
    ) -> ApplicatorResult:
        if not MODULE_NAME_RE.match(dependency_name or ""):
            return _reject("nom de module invalide")
        content = _content(file_path, current_content)
        try:
            manifest = ast.literal_eval(content.lstrip())
            tree = ast.parse(content)
        except (SyntaxError, ValueError) as exc:
            return _reject(f"manifeste non littéral ({exc})")
        if known_modules is None or dependency_graph is None:
            return _reject("modules connus ou graphe de dépendances absents")
        if dependency_name not in known_modules:
            return _reject("dépendance inexistante dans les sources indexées")
        if dependency_name == module_name:
            return _reject("cycle de dépendance (le module lui-même)")
        # The whole closure of the new dependency must be known to rule out a cycle.
        seen, todo = set(), [dependency_name]
        while todo:
            current = todo.pop()
            if current == module_name:
                return _reject("cycle de dépendance")
            if current in seen:
                continue
            seen.add(current)
            if current not in dependency_graph:
                return _reject(f"graphe de dépendances incomplet ({current} inconnu) : cycle invérifiable")
            todo.extend(dependency_graph[current])
        depends = manifest.get("depends", []) if isinstance(manifest, dict) else None
        if not isinstance(depends, list):
            return _reject("clé depends absente ou non littérale")
        if dependency_name in depends:
            return _reject("dépendance déjà présente")
        dict_node = tree.body[0].value if tree.body and isinstance(tree.body[0], ast.Expr) else None
        if not isinstance(dict_node, ast.Dict):
            return _reject("manifeste qui n'est pas un dictionnaire littéral")
        list_node = next(
            (v for k, v in zip(dict_node.keys, dict_node.values)
             if isinstance(k, ast.Constant) and k.value == "depends"),
            None,
        )
        if not isinstance(list_node, ast.List):
            return _reject("depends n'est pas une liste littérale")
        offsets = _line_offsets(content)
        if list_node.elts:
            last = list_node.elts[-1]
            position = _char_offset(content, offsets, last.end_lineno, last.end_col_offset)
            quote = content[_char_offset(content, offsets, last.lineno, last.col_offset)]
            quote = quote if quote in "'\"" else "'"
            if list_node.lineno != list_node.end_lineno:
                line = content.split("\n")[last.lineno - 1]
                indent = line[: len(line) - len(line.lstrip())]
                insertion = f",\n{indent}{quote}{dependency_name}{quote}"
            else:
                insertion = f", {quote}{dependency_name}{quote}"
        else:
            position = _char_offset(content, offsets, list_node.lineno, list_node.col_offset) + 1
            insertion = f"'{dependency_name}'"
        new_content = content[:position] + insertion + content[position:]
        try:
            new_manifest = ast.literal_eval(new_content.lstrip())
        except (SyntaxError, ValueError) as exc:
            return _reject(f"manifeste invalide après insertion ({exc})")
        expected = dict(manifest, depends=[*depends, dependency_name])
        if new_manifest != expected:
            return _reject("postcondition du manifeste non respectée")
        return _done(file_path, content, new_content)


# ---------------------------------------------------------------- CSV

def _csv_cells(line: str) -> list[tuple[int, int]] | None:
    """(start, end) of each raw cell of a single physical CSV line."""
    cells, start, index, quoted = [], 0, 0, False
    while index <= len(line):
        if index == len(line) or (line[index] == "," and not quoted):
            cells.append((start, index))
            start = index + 1
        elif line[index] == '"':
            quoted = not quoted
        index += 1
    return None if quoted else cells


class CsvValueApplicator:
    """Replaces one cell; every other byte of the file is kept."""

    @staticmethod
    def replace_value(
        file_path: pathlib.Path,
        column_index: int,
        old_value: str,
        new_value: str,
        row_filter_col: int = -1,
        row_filter_val: str = "",
        current_content: str | None = None,
    ) -> ApplicatorResult:
        if any(c in new_value for c in "\r\n"):
            return _reject("nouvelle valeur multiligne")
        content = _content(file_path, current_content)
        try:
            rows = list(csv.reader(io.StringIO(content)))
        except csv.Error as exc:
            return _reject(f"CSV invalide ({exc})")
        if any("\n" in cell or "\r" in cell for row in rows for cell in row):
            return _reject("cellule CSV multiligne non prise en charge pour préservation exacte")
        lines = content.split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]
        if len(rows) != len(lines):
            return _reject("lignes CSV impossibles à aligner")
        matches = [
            i for i, row in enumerate(rows)
            if column_index < len(row) and row[column_index] == old_value
            and (row_filter_col < 0 or (row_filter_col < len(row) and row[row_filter_col] == row_filter_val))
        ]
        if not matches:
            return _reject("cellule CSV introuvable")
        if len(matches) > 1:
            return _reject("cellule CSV non unique", f"{len(matches)} rows matched")
        row_index = matches[0]
        line = lines[row_index]
        cells = _csv_cells(line)
        if cells is None or len(cells) != len(rows[row_index]):
            return _reject("ligne CSV non analysable sans ambiguïté")
        start, end = cells[column_index]
        raw = line[start:end]
        quoted = raw.startswith('"')
        if quoted or any(c in new_value for c in ',"'):
            replacement = '"' + new_value.replace('"', '""') + '"'
        else:
            replacement = new_value
        all_lines = content.split("\n")
        all_lines[row_index] = line[:start] + replacement + line[end:]
        return _done(file_path, content, "\n".join(all_lines))


# ---------------------------------------------------------------- dispatcher

def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"entier attendu, reçu {value!r}")
    return value


def apply_typed_operation(
    module_path: pathlib.Path,
    op: dict[str, Any],
    file_buffers: dict[str, str] | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[ApplicatorResult, str]:
    """Dispatch a typed operation to its deterministic applicator."""
    op_type = op.get("type", "exact_text_replace")
    rel_file = str(op.get("file", "")).strip().replace("\\", "/")
    module_path = pathlib.Path(module_path)
    target_path = (module_path / rel_file).resolve()
    if target_path.suffix.lower() == ".js":
        return _reject("JavaScript non validé", "JS auto-application forbidden"), rel_file
    try:
        target_path.relative_to(module_path.resolve())
    except ValueError:
        return _reject("chemin hors module", "path traversal rejected"), rel_file
    if (module_path / rel_file).is_symlink():
        return _reject("lien symbolique refusé"), rel_file
    current = file_buffers.get(rel_file) if file_buffers else None
    ctx = context or {}
    try:
        if op_type == "exact_text_replace":
            res = ExactTextApplicator.apply(target_path, str(op.get("old", "")), str(op.get("new", "")), current_content=current)
        elif op_type == "replace_import":
            res = PythonImportApplicator.replace_import(
                target_path, str(op.get("old_module", "")), str(op.get("new_module", "")), str(op.get("name", "")),
                current_content=current, target_line=_int_or_none(op.get("line")),
            )
        elif op_type == "add_import":
            res = PythonImportApplicator.add_import(target_path, str(op.get("module", "")), str(op.get("name", "")), current_content=current)
        elif op_type == "rename_dict_key":
            res = PythonDictKeyApplicator.rename_key(
                target_path, str(op.get("old_key", "")), str(op.get("new_key", "")),
                current_content=current, target_line=_int_or_none(op.get("line")),
            )
        elif op_type == "xml_set_attribute":
            res = XmlAttributeApplicator.set_attribute(
                target_path, str(op.get("tag", "")), str(op.get("attribute", "")), str(op.get("old_value", "")),
                str(op.get("new_value", "")), str(op.get("identifier", "")), current_content=current,
            )
        elif op_type == "xml_replace_xpath":
            tree = ctx.get("target_view_tree")
            if not tree:
                return _reject("arbre de vues cibles absent pour valider l'ancre XPath"), rel_file
            res = XmlXPathApplicator.replace_expr(
                target_path, str(op.get("old_expr", "")), str(op.get("new_expr", "")), current_content=current,
                target_view_tree=tree, require_anchor=True, module_name=str(ctx.get("module_name", "")),
            )
        elif op_type == "manifest_add_dependency":
            known, graph = ctx.get("known_modules"), ctx.get("dependency_graph")
            if not known or graph is None:
                return _reject("informations de dépendances (known_modules ou dependency_graph) absentes"), rel_file
            res = ManifestDependencyApplicator.add_dependency(
                target_path, str(op.get("dependency", "")), current_content=current, known_modules=known,
                dependency_graph=graph, module_name=str(ctx.get("module_name", module_path.name)),
            )
        elif op_type == "csv_replace_value":
            column = _int_or_none(op.get("column"))
            if column is None or column < 0:
                return _reject("colonne CSV invalide"), rel_file
            filter_column = _int_or_none(op.get("filter_column"))
            res = CsvValueApplicator.replace_value(
                target_path, column, str(op.get("old_value", "")), str(op.get("new_value", "")),
                -1 if filter_column is None else filter_column, str(op.get("filter_value", "")),
                current_content=current,
            )
        else:
            return _reject(f"type d'opération inconnu ({op_type})"), rel_file
    except (ValueError, TypeError, IndexError, UnicodeError) as exc:
        return _reject(f"paramètres d'opération invalides ({exc})"), rel_file
    return res, rel_file
