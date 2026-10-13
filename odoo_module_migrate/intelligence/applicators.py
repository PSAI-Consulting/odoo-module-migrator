# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Deterministic typed structured applicators for Odoo code migrations.

Every applicator:
1. Verifies expected precondition (e.g. target node/text is unique and unambiguous).
2. Performs the modification using AST / tree coordinates.
3. Produces a minimal unified diff.
4. Validates postcondition (ast.parse, lxml.etree, csv parsing).
5. Preserves comments, shebangs, encodings, docstrings and formatting.
6. Rejects JavaScript files from automated modification.
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

from lxml import etree

from .. import tools

logger = logging.getLogger(__name__)


@dataclass
class ApplicatorResult:
    success: bool
    status: str
    error: str = ""
    diff: str = ""
    new_content: str = ""
    lines_changed: int = 0


def generate_diff(old_text: str, new_text: str, filename: str) -> tuple[str, int]:
    """Generate a clean unified diff and count lines changed."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}",
    ))
    diff_str = "".join(diff_lines)
    changed = sum(1 for line in diff_lines if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
    return diff_str, changed


def validate_syntax(path: pathlib.Path | str, content: str) -> tuple[bool, str]:
    """Strictly validate file syntax according to its extension."""
    suffix = pathlib.Path(path).suffix.lower()
    try:
        if suffix == ".py":
            ast.parse(content)
        elif suffix == ".xml":
            etree.fromstring(content.encode("utf-8"), parser=etree.XMLParser(recover=False))
        elif suffix == ".csv":
            reader = csv.reader(io.StringIO(content))
            list(reader)
        elif suffix in {".json"}:
            import json
            json.loads(content)
        elif suffix == ".js":
            return False, "modification automatique JavaScript non supportée"
        else:
            return False, f"extension non validable ({suffix})"
    except (SyntaxError, ValueError, etree.XMLSyntaxError, csv.Error) as exc:
        return False, f"syntaxe invalide après édition: {exc}"
    return True, ""


# ---------------------------------------------------------------------------
# 1. Exact Text Replacement Applicator (Safe Fallback)
# ---------------------------------------------------------------------------

class ExactTextApplicator:
    """Safely replaces an exact, unambiguous text snippet with validation."""

    @staticmethod
    def apply(
        file_path: pathlib.Path,
        old_text: str,
        new_text: str,
        current_content: str | None = None,
        max_chars: int = 8000,
    ) -> ApplicatorResult:
        if file_path.suffix.lower() == ".js":
            return ApplicatorResult(False, "rejected: JavaScript non validé", "JS auto-application forbidden")
        if not old_text:
            return ApplicatorResult(False, "rejected: texte attendu vide", "old text is empty")
        if len(old_text) > max_chars or len(new_text) > max_chars:
            return ApplicatorResult(False, "rejected: édition trop volumineuse", "edit exceeds character limit")

        content = current_content if current_content is not None else tools._read_content(file_path)
        count = content.count(old_text)
        if count == 0:
            return ApplicatorResult(False, "rejected: texte attendu absent", f"snippet not found in {file_path.name}")
        if count > 1:
            return ApplicatorResult(False, "rejected: texte attendu non unique", f"snippet found {count} times in {file_path.name}")

        new_content = content.replace(old_text, new_text, 1)
        valid, reason = validate_syntax(file_path, new_content)
        if not valid:
            return ApplicatorResult(False, f"rejected: {reason}", reason)

        diff, lines_changed = generate_diff(content, new_content, file_path.name)
        return ApplicatorResult(True, "applied", diff=diff, new_content=new_content, lines_changed=lines_changed)


# ---------------------------------------------------------------------------
# 2. Python Import Applicator (AST-coordinated)
# ---------------------------------------------------------------------------

class PythonImportApplicator:
    """Modifies or adds Python import statements safely using AST positions."""

    @staticmethod
    def replace_import(
        file_path: pathlib.Path,
        old_module: str,
        new_module: str,
        imported_name: str = "",
        current_content: str | None = None,
        target_line: int | None = None,
    ) -> ApplicatorResult:
        content = current_content if current_content is not None else tools._read_content(file_path)
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return ApplicatorResult(False, f"rejected: syntaxe initiale invalide ({exc})", str(exc))

        found_nodes: list[ast.stmt] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                dots = "." * getattr(node, "level", 0)
                full_mod = f"{dots}{node.module or ''}"
                mod_matches = (node.module == old_module or full_mod == old_module)
                name_matches = any(alias.name == old_module for alias in node.names)
                if (mod_matches or (node.module is None and name_matches)) and (
                    not imported_name or any(alias.name == imported_name for alias in node.names)
                ):
                    found_nodes.append(node)
            elif isinstance(node, ast.Import) and any(alias.name == old_module for alias in node.names):
                found_nodes.append(node)

        if target_line is not None:
            matching = [n for n in found_nodes if n.lineno == target_line]
            if matching:
                found_nodes = matching

        if not found_nodes:
            return ApplicatorResult(False, "rejected: import attendu absent", f"import of {old_module} not found")
        if len(found_nodes) > 1:
            return ApplicatorResult(False, "rejected: import ambigu", f"{len(found_nodes)} matching imports found")

        target_node = found_nodes[0]
        lines = content.splitlines(keepends=True)
        start_line = target_node.lineno - 1
        end_line = getattr(target_node, "end_lineno", target_node.lineno)

        orig_chunk = "".join(lines[start_line:end_line])
        indent_match = re.match(r"^(\s*)", orig_chunk)
        indent = indent_match.group(1) if indent_match else ""

        # Preserve trailing comment on the import line
        last_line_raw = lines[end_line - 1].rstrip("\r\n")
        comment_match = re.search(r"(\s*#.*)$", last_line_raw)
        trailing_comment = comment_match.group(1) if comment_match else ""

        if isinstance(target_node, ast.ImportFrom):
            dots = "." * getattr(target_node, "level", 0)
            if target_node.module is None:
                aliases = []
                for alias in target_node.names:
                    if alias.name == old_module:
                        alias_part = new_module if not alias.asname else f"{new_module} as {alias.asname}"
                    else:
                        alias_part = alias.name if not alias.asname else f"{alias.name} as {alias.asname}"
                    aliases.append(alias_part)
                new_chunk = f"{indent}from {dots} import {', '.join(aliases)}{trailing_comment}\n"
            else:
                names_str = ", ".join(alias.name if not alias.asname else f"{alias.name} as {alias.asname}" for alias in target_node.names)
                new_chunk = f"{indent}from {new_module} import {names_str}{trailing_comment}\n"
        else:
            aliases = []
            for alias in target_node.names:
                if alias.name == old_module:
                    alias_part = new_module if not alias.asname else f"{new_module} as {alias.asname}"
                else:
                    alias_part = alias.name if not alias.asname else f"{alias.name} as {alias.asname}"
                aliases.append(alias_part)
            new_chunk = f"{indent}import {', '.join(aliases)}{trailing_comment}\n"

        new_lines = lines[:start_line] + [new_chunk] + lines[end_line:]
        new_content = "".join(new_lines)

        valid, reason = validate_syntax(file_path, new_content)
        if not valid:
            return ApplicatorResult(False, f"rejected: {reason}", reason)

        diff, lines_changed = generate_diff(content, new_content, file_path.name)
        return ApplicatorResult(True, "applied", diff=diff, new_content=new_content, lines_changed=lines_changed)

    @staticmethod
    def add_import(
        file_path: pathlib.Path,
        module: str,
        name: str,
        current_content: str | None = None,
    ) -> ApplicatorResult:
        content = current_content if current_content is not None else tools._read_content(file_path)
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return ApplicatorResult(False, f"rejected: syntaxe invalide ({exc})", str(exc))

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == module and any(alias.name == name for alias in node.names):
                return ApplicatorResult(False, "rejected: import déjà présent", f"{name} already imported from {module}")

        lines = content.splitlines(keepends=True)
        insert_line_idx = 0

        # Preserve shebang & encoding comments
        while insert_line_idx < len(lines):
            stripped = lines[insert_line_idx].strip()
            if stripped.startswith("#!") or "coding:" in stripped or "coding=" in stripped or stripped == "":
                insert_line_idx += 1
            else:
                break

        # Preserve module docstring
        if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
            doc_node = tree.body[0]
            doc_end = getattr(doc_node, "end_lineno", doc_node.lineno)
            insert_line_idx = max(insert_line_idx, doc_end)

        # Must be strictly placed AFTER any __future__ imports
        future_nodes = [
            node for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        ]
        if future_nodes:
            max_future = max(getattr(f, "end_lineno", f.lineno) for f in future_nodes)
            insert_line_idx = max(insert_line_idx, max_future)

        # If there are other top-level imports, place after them
        import_nodes = [
            node for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom)) and getattr(node, "module", "") != "__future__"
        ]
        if import_nodes:
            max_import = max(getattr(im, "end_lineno", im.lineno) for im in import_nodes)
            insert_line_idx = max(insert_line_idx, max_import)

        new_import_stmt = f"from {module} import {name}\n"
        new_lines = list(lines)
        new_lines.insert(insert_line_idx, new_import_stmt)
        new_content = "".join(new_lines)

        valid, reason = validate_syntax(file_path, new_content)
        if not valid:
            return ApplicatorResult(False, f"rejected: {reason}", reason)

        diff, lines_changed = generate_diff(content, new_content, file_path.name)
        return ApplicatorResult(True, "applied", diff=diff, new_content=new_content, lines_changed=lines_changed)


# ---------------------------------------------------------------------------
# 3. Python Dict Key Renaming Applicator (AST Position-Precise)
# ---------------------------------------------------------------------------

class PythonDictKeyApplicator:
    """Renames keys in dictionary literals using exact AST coordinates."""

    @staticmethod
    def rename_key(
        file_path: pathlib.Path,
        old_key: str,
        new_key: str,
        current_content: str | None = None,
        target_line: int | None = None,
    ) -> ApplicatorResult:
        content = current_content if current_content is not None else tools._read_content(file_path)
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return ApplicatorResult(False, f"rejected: syntaxe invalide ({exc})", str(exc))

        matched_keys: list[ast.Constant] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k in node.keys:
                    if isinstance(k, ast.Constant) and k.value == old_key:
                        matched_keys.append(k)

        if not matched_keys:
            return ApplicatorResult(False, "rejected: clé absente des dictionnaires", f"key {old_key!r} not in any dict")

        if len(matched_keys) > 1 and target_line is None:
            return ApplicatorResult(
                False,
                "rejected: clé présente dans plusieurs dictionnaires",
                f"{len(matched_keys)} dictionaries contain key {old_key!r}; target_line required for disambiguation",
            )

        if target_line is not None:
            filtered = [k for k in matched_keys if k.lineno == target_line]
            if len(filtered) != 1:
                return ApplicatorResult(
                    False,
                    "rejected: clé ambiguë sur la ligne cible",
                    f"expected 1 match on line {target_line}, found {len(filtered)}",
                )
            target_key = filtered[0]
        else:
            target_key = matched_keys[0]

        # Use exact line and column slice
        lines = content.splitlines(keepends=True)
        line_idx = target_key.lineno - 1
        line_text = lines[line_idx]

        start_col = target_key.col_offset
        end_col = getattr(target_key, "end_col_offset", start_col + len(old_key) + 2)

        raw_slice = line_text[start_col:end_col]
        if not (
            raw_slice.startswith(("'", '"'))
            and raw_slice.endswith(("'", '"'))
            and raw_slice[1:-1] == old_key
        ):
            single_quoted = f"'{old_key}'"
            double_quoted = f'"{old_key}"'
            found_pos = -1
            found_quote = "'"
            if line_text.count(single_quoted) == 1 and line_text.count(double_quoted) == 0:
                found_pos = line_text.find(single_quoted)
                found_quote = "'"
            elif line_text.count(double_quoted) == 1 and line_text.count(single_quoted) == 0:
                found_pos = line_text.find(double_quoted)
                found_quote = '"'

            if found_pos >= 0:
                start_col = found_pos
                end_col = found_pos + len(old_key) + 2
                raw_slice = line_text[start_col:end_col]
                quote = found_quote
            else:
                return ApplicatorResult(
                    False,
                    "rejected: décalage de colonne ou clé non concordante",
                    f"slice at offset [{start_col}:{end_col}] ({raw_slice!r}) does not match {old_key!r}",
                )
        else:
            quote = "'" if raw_slice.startswith("'") else '"'

        new_slice = f"{quote}{new_key}{quote}"

        new_line_text = line_text[:start_col] + new_slice + line_text[end_col:]
        lines[line_idx] = new_line_text
        new_content = "".join(lines)

        valid, reason = validate_syntax(file_path, new_content)
        if not valid:
            return ApplicatorResult(False, f"rejected: {reason}", reason)

        diff, lines_changed = generate_diff(content, new_content, file_path.name)
        return ApplicatorResult(True, "applied", diff=diff, new_content=new_content, lines_changed=lines_changed)


# ---------------------------------------------------------------------------
# 4. XML Attribute Applicator (lxml Element-Targeted)
# ---------------------------------------------------------------------------

class XmlAttributeApplicator:
    """Modifies XML attributes strictly targeting elements by tag and identifier."""

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
        content = current_content if current_content is not None else tools._read_content(file_path)
        try:
            tree = etree.fromstring(content.encode("utf-8"), parser=etree.XMLParser(recover=False))
        except etree.XMLSyntaxError as exc:
            return ApplicatorResult(False, f"rejected: XML initial invalide ({exc})", str(exc))

        matched_elements = []
        for el in tree.iter(element_tag):
            if el.get(attribute_name) == old_value:
                if not identifier:
                    matched_elements.append(el)
                else:
                    attrs = [str(v) for v in el.attrib.values()]
                    if identifier in attrs or any(identifier in a for a in attrs):
                        matched_elements.append(el)

        if not matched_elements:
            return ApplicatorResult(
                False,
                "rejected: élément XML introuvable",
                f"<{element_tag} {attribute_name}={old_value!r}> not found with identifier {identifier!r}",
            )
        if len(matched_elements) > 1:
            return ApplicatorResult(
                False,
                "rejected: élément XML non unique",
                f"{len(matched_elements)} elements matched <{element_tag} {attribute_name}={old_value!r}>",
            )

        target_el = matched_elements[0]
        sourceline = target_el.sourceline or 1
        lines = content.splitlines(keepends=True)

        start_line_idx = max(0, sourceline - 1)
        tag_open = f"<{element_tag}"
        if tag_open not in lines[start_line_idx]:
            for b_idx in range(max(0, start_line_idx - 2), start_line_idx):
                if tag_open in lines[b_idx]:
                    start_line_idx = b_idx
                    break

        end_line_idx = start_line_idx
        tag_chunk = ""
        found_close = False
        while end_line_idx < len(lines):
            tag_chunk += lines[end_line_idx]
            in_q = None
            for char in tag_chunk:
                if char in ("'", '"'):
                    if in_q == char:
                        in_q = None
                    elif in_q is None:
                        in_q = char
                elif char == ">" and in_q is None:
                    found_close = True
                    break
            if found_close:
                break
            end_line_idx += 1

        attr_pattern = rf"""\b{re.escape(attribute_name)}\s*=\s*(?P<q>["']){re.escape(old_value)}(?P=q)"""
        match = re.search(attr_pattern, tag_chunk, re.DOTALL)
        if not match:
            return ApplicatorResult(
                False,
                "rejected: attribut introuvable dans la balise de l'élément",
                f"attribute {attribute_name}={old_value!r} not found in <{element_tag}> chunk",
            )

        q = match.group("q")
        new_attr_str = f"{attribute_name}={q}{new_value}{q}"
        new_tag_chunk = tag_chunk[:match.start()] + new_attr_str + tag_chunk[match.end():]

        new_lines = lines[:start_line_idx] + [new_tag_chunk] + lines[end_line_idx + 1:]
        new_content = "".join(new_lines)

        valid, reason = validate_syntax(file_path, new_content)
        if not valid:
            return ApplicatorResult(False, f"rejected: {reason}", reason)

        diff, lines_changed = generate_diff(content, new_content, file_path.name)
        return ApplicatorResult(True, "applied", diff=diff, new_content=new_content, lines_changed=lines_changed)


# ---------------------------------------------------------------------------
# 5. XML XPath Applicator (Anchor Verified)
# ---------------------------------------------------------------------------

class TargetViewTrees:
    """Collection of target view trees supporting XPath queries."""

    def __init__(self, arches: Any = None):
        if isinstance(arches, dict):
            self.trees = [t for t in arches.values() if hasattr(t, "xpath")]
        elif isinstance(arches, (list, tuple, set)):
            self.trees = [t for t in arches if hasattr(t, "xpath")]
        elif hasattr(arches, "xpath"):
            self.trees = [arches]
        else:
            self.trees = []

    def xpath(self, expr: str) -> list[Any]:
        results = []
        for tree in self.trees:
            try:
                res = tree.xpath(expr)
                if res:
                    if isinstance(res, list):
                        results.extend(res)
                    else:
                        results.append(res)
            except Exception as exc:  # noqa: BLE001
                logger.debug("XPath evaluation error on view tree: %s", exc)
                continue
        return results

    def __bool__(self) -> bool:
        return bool(self.trees)


class XmlXPathApplicator:
    """Updates xpath expr expressions with syntax and anchor verification."""

    @staticmethod
    def replace_expr(
        file_path: pathlib.Path,
        old_expr: str,
        new_expr: str,
        current_content: str | None = None,
        target_view_tree: Any | None = None,
        require_anchor: bool = False,
    ) -> ApplicatorResult:
        content = current_content if current_content is not None else tools._read_content(file_path)
        pattern = rf"""(?P<prefix><xpath[^>]+expr\s*=\s*)(?P<quote>["']){re.escape(old_expr)}(?P=quote)"""
        matches = list(re.finditer(pattern, content))
        if not matches:
            return ApplicatorResult(False, "rejected: xpath expr introuvable", f"xpath with expr={old_expr!r} not found")
        if len(matches) > 1:
            return ApplicatorResult(False, "rejected: xpath expr non unique", f"{len(matches)} matching xpath expressions found")

        # Verify new_expr is valid xpath expression
        try:
            etree.XPath(new_expr)
        except etree.XPathSyntaxError as exc:
            return ApplicatorResult(False, f"rejected: nouvelle expression XPath invalide ({exc})", str(exc))

        if require_anchor and not target_view_tree:
            return ApplicatorResult(
                False,
                "rejected: arbre de vues cibles absent pour valider l'ancre XPath",
                "target_view_tree required to validate xpath expression anchor",
            )

        # Check against target view tree anchor if provided
        if target_view_tree:
            try:
                anchor_matches = target_view_tree.xpath(new_expr)
                if not anchor_matches:
                    return ApplicatorResult(False, "rejected: ancre XPath introuvable dans la vue cible", f"new_expr {new_expr!r} not in target view")
            except Exception as exc:  # noqa: BLE001
                return ApplicatorResult(
                    False,
                    f"rejected: échec de l'évaluation XPath sur la vue cible ({exc})",
                    str(exc),
                )

        def repl(m: re.Match[str]) -> str:
            prefix = m.group("prefix")
            q = m.group("quote")
            return f"{prefix}{q}{new_expr}{q}"

        new_content = re.sub(pattern, repl, content, count=1)
        valid, reason = validate_syntax(file_path, new_content)
        if not valid:
            return ApplicatorResult(False, f"rejected: {reason}", reason)

        diff, lines_changed = generate_diff(content, new_content, file_path.name)
        return ApplicatorResult(True, "applied", diff=diff, new_content=new_content, lines_changed=lines_changed)


# ---------------------------------------------------------------------------
# 6. Manifest Dependency Applicator (Cycle & Existence Verified)
# ---------------------------------------------------------------------------

class ManifestDependencyApplicator:
    """Adds a dependency to __manifest__.py verifying existence and absence of cycles."""

    @staticmethod
    def add_dependency(
        file_path: pathlib.Path,
        dependency_name: str,
        current_content: str | None = None,
        known_modules: set[str] | None = None,
        dependency_graph: dict[str, list[str]] | None = None,
        module_name: str = "",
    ) -> ApplicatorResult:
        content = current_content if current_content is not None else tools._read_content(file_path)
        try:
            manifest_dict = ast.literal_eval(content)
        except Exception as exc:  # noqa: BLE001
            return ApplicatorResult(False, f"rejected: manifeste non littéral ({exc})", str(exc))

        # 1. Existence check
        if known_modules is not None and dependency_name not in known_modules:
            return ApplicatorResult(
                False,
                "rejected: dépendance inexistante",
                f"module {dependency_name!r} not found in known target modules",
            )

        # 2. Cycle check
        if dependency_graph and module_name:
            visited = set()
            stack = [dependency_name]
            while stack:
                curr = stack.pop()
                if curr == module_name:
                    return ApplicatorResult(
                        False,
                        "rejected: cycle de dépendance",
                        f"adding {dependency_name} creates a circular dependency with {module_name}",
                    )
                if curr not in visited:
                    visited.add(curr)
                    stack.extend(dependency_graph.get(curr, []))

        depends = manifest_dict.get("depends", [])
        if dependency_name in depends:
            return ApplicatorResult(False, "rejected: dépendance déjà présente", f"{dependency_name} already in depends")

        match = re.search(r"""(['"]depends['"]\s*:\s*\[)([^\]]*?)(\])""", content, re.DOTALL)
        if not match:
            return ApplicatorResult(False, "rejected: clé depends introuvable", "depends list not found in manifest")

        head, inner, tail = match.group(1), match.group(2), match.group(3)
        quote = "'" if "'" in inner or '"' not in inner else '"'
        new_dep_str = f"{quote}{dependency_name}{quote}"

        if inner.strip():
            if "\n" in inner:
                last_line = inner.rstrip().splitlines()[-1]
                indent = " " * (len(last_line) - len(last_line.lstrip()))
                new_inner = inner.rstrip()
                if not new_inner.endswith(","):
                    new_inner += ","
                new_inner += f"\n{indent}{new_dep_str},\n"
            else:
                new_inner = inner.strip()
                if not new_inner.endswith(","):
                    new_inner += ", "
                else:
                    new_inner += " "
                new_inner += f"{new_dep_str}"
        else:
            new_inner = f"\n        {new_dep_str},\n    "

        new_content = content[:match.start()] + head + new_inner + tail + content[match.end():]
        valid, reason = validate_syntax(file_path, new_content)
        if not valid:
            return ApplicatorResult(False, f"rejected: {reason}", reason)

        diff, lines_changed = generate_diff(content, new_content, file_path.name)
        return ApplicatorResult(True, "applied", diff=diff, new_content=new_content, lines_changed=lines_changed)


# ---------------------------------------------------------------------------
# 7. CSV Value Applicator (Byte & Format Preserving)
# ---------------------------------------------------------------------------

class CsvValueApplicator:
    """Updates CSV cell value in-place while keeping other lines byte-for-byte identical."""

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
        if current_content is not None:
            content = current_content
        else:
            raw = file_path.read_bytes()
            content = raw.decode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8", errors="replace")
        try:
            reader = list(csv.reader(io.StringIO(content)))
        except Exception as exc:  # noqa: BLE001
            return ApplicatorResult(False, f"rejected: CSV invalide ({exc})", str(exc))

        # Reject multiline CSV cells as exact byte-for-byte preservation across lines is not supported
        for row in reader:
            if any("\n" in cell or "\r" in cell for cell in row):
                return ApplicatorResult(
                    False,
                    "rejected: cellule CSV multiligne non prise en charge pour préservation exacte",
                    "multiline CSV cell cannot be preserved byte-for-byte",
                )

        matched_row_indices = []
        for i, row in enumerate(reader):
            if column_index < len(row) and row[column_index] == old_value and (
                row_filter_col == -1 or (row_filter_col < len(row) and row[row_filter_col] == row_filter_val)
            ):
                matched_row_indices.append(i)

        if not matched_row_indices:
            return ApplicatorResult(False, "rejected: cellule CSV introuvable", f"no row matched {old_value!r}")
        if len(matched_row_indices) > 1 and row_filter_col == -1:
            return ApplicatorResult(False, "rejected: cellule CSV non unique", f"{len(matched_row_indices)} rows matched without filter")

        target_row_idx = matched_row_indices[0]
        lines = content.splitlines(keepends=True)

        target_line = lines[target_row_idx]
        # Parse only this row to find cell representation
        row_cells = next(csv.reader([target_line]))
        row_cells[column_index] = new_value

        out = io.StringIO()
        csv.writer(out, lineterminator="").writerow(row_cells)
        ending = "\r\n" if target_line.endswith("\r\n") else ("\n" if target_line.endswith("\n") else "")
        new_target_line = out.getvalue() + ending

        lines[target_row_idx] = new_target_line
        new_content = "".join(lines)

        valid, reason = validate_syntax(file_path, new_content)
        if not valid:
            return ApplicatorResult(False, f"rejected: {reason}", reason)

        diff, lines_changed = generate_diff(content, new_content, file_path.name)
        return ApplicatorResult(True, "applied", diff=diff, new_content=new_content, lines_changed=lines_changed)


# ---------------------------------------------------------------------------
# Central Dispatcher
# ---------------------------------------------------------------------------

def apply_typed_operation(
    module_path: pathlib.Path,
    op: dict[str, Any],
    file_buffers: dict[str, str] | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[ApplicatorResult, str]:
    """Dispatch a typed operation to the corresponding deterministic applicator."""
    op_type = op.get("type", "exact_text_replace")
    rel_file = str(op.get("file", "")).strip().replace("\\", "/")
    target_path = (module_path / rel_file).resolve()

    if target_path.suffix.lower() == ".js":
        return ApplicatorResult(False, "rejected: JavaScript non validé", "JS auto-application forbidden"), rel_file

    try:
        target_path.relative_to(module_path.resolve())
    except ValueError:
        return ApplicatorResult(False, "rejected: chemin hors module", "path traversal rejected"), rel_file

    current_text = None
    if file_buffers and rel_file in file_buffers:
        current_text = file_buffers[rel_file]

    ctx = context or {}

    if op_type == "exact_text_replace":
        old_val = str(op.get("old", ""))
        new_val = str(op.get("new", ""))
        res = ExactTextApplicator.apply(target_path, old_val, new_val, current_content=current_text)
        return res, rel_file

    if op_type == "replace_import":
        old_mod = str(op.get("old_module", ""))
        new_mod = str(op.get("new_module", ""))
        name = str(op.get("name", ""))
        res = PythonImportApplicator.replace_import(target_path, old_mod, new_mod, name, current_content=current_text)
        return res, rel_file

    if op_type == "add_import":
        mod = str(op.get("module", ""))
        name = str(op.get("name", ""))
        res = PythonImportApplicator.add_import(target_path, mod, name, current_content=current_text)
        return res, rel_file

    if op_type == "rename_dict_key":
        old_k = str(op.get("old_key", ""))
        new_k = str(op.get("new_key", ""))
        t_line = op.get("line")
        target_line = int(t_line) if t_line is not None else None
        res = PythonDictKeyApplicator.rename_key(target_path, old_k, new_k, current_content=current_text, target_line=target_line)
        return res, rel_file

    if op_type == "xml_set_attribute":
        tag = str(op.get("tag", ""))
        attr = str(op.get("attribute", ""))
        old_v = str(op.get("old_value", ""))
        new_v = str(op.get("new_value", ""))
        ident = str(op.get("identifier", ""))
        res = XmlAttributeApplicator.set_attribute(target_path, tag, attr, old_v, new_v, ident, current_content=current_text)
        return res, rel_file

    if op_type == "xml_replace_xpath":
        old_e = str(op.get("old_expr", ""))
        new_e = str(op.get("new_expr", ""))
        target_tree = ctx.get("target_view_tree")
        if not target_tree:
            return ApplicatorResult(
                False,
                "rejected: arbre de vues cibles absent pour valider l'ancre XPath",
                "target_view_tree required to validate xpath expression anchor",
            ), rel_file
        res = XmlXPathApplicator.replace_expr(
            target_path, old_e, new_e, current_content=current_text, target_view_tree=target_tree, require_anchor=True
        )
        return res, rel_file

    if op_type == "manifest_add_dependency":
        dep = str(op.get("dependency", ""))
        known_mods = ctx.get("known_modules")
        dep_graph = ctx.get("dependency_graph")
        if not known_mods or dep_graph is None:
            return ApplicatorResult(
                False,
                "rejected: informations de dépendances (known_modules ou dependency_graph) absentes",
                "known_modules and dependency_graph required to validate dependency addition",
            ), rel_file
        res = ManifestDependencyApplicator.add_dependency(
            target_path,
            dep,
            current_content=current_text,
            known_modules=known_mods,
            dependency_graph=dep_graph,
            module_name=str(ctx.get("module_name", module_path.name)),
        )
        return res, rel_file

    if op_type == "csv_replace_value":
        col = int(op.get("column", 0))
        old_c = str(op.get("old_value", ""))
        new_c = str(op.get("new_value", ""))
        f_col = int(op.get("filter_column", -1))
        f_val = str(op.get("filter_value", ""))
        res = CsvValueApplicator.replace_value(target_path, col, old_c, new_c, f_col, f_val, current_content=current_text)
        return res, rel_file

    return ApplicatorResult(False, f"rejected: type d'opération inconnu ({op_type})", "unknown operation type"), rel_file
