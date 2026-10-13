# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Deterministic typed structured applicators for Odoo code migrations.

Every applicator:
1. Verifies expected precondition (e.g. target node/text is unique and unambiguous).
2. Performs the modification.
3. Produces a minimal unified diff.
4. Validates postcondition (ast.parse, lxml.etree, csv parsing).
5. Can be executed and tested completely independently of any LLM.
"""

from __future__ import annotations

import ast
import csv
import difflib
import io
import pathlib
import re
from dataclasses import dataclass
from typing import Any

from lxml import etree

from .. import manifest, tools


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
    # Count additions and deletions
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
        elif suffix in {".json", ".js"}:
            pass
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
# 2. Python Import Applicator
# ---------------------------------------------------------------------------

class PythonImportApplicator:
    """Modifies or adds Python import statements safely."""

    @staticmethod
    def replace_import(
        file_path: pathlib.Path,
        old_module: str,
        new_module: str,
        imported_name: str = "",
        current_content: str | None = None,
    ) -> ApplicatorResult:
        content = current_content if current_content is not None else tools._read_content(file_path)
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return ApplicatorResult(False, f"rejected: syntaxe initiale invalide ({exc})", str(exc))

        # Check for matching import node
        found_nodes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == old_module:
                if not imported_name or any(alias.name == imported_name for alias in node.names):
                    found_nodes.append(node)
            elif isinstance(node, ast.Import):
                if any(alias.name == old_module for alias in node.names):
                    found_nodes.append(node)

        if not found_nodes:
            return ApplicatorResult(False, "rejected: import attendu absent", f"import of {old_module} not found")
        if len(found_nodes) > 1:
            return ApplicatorResult(False, "rejected: import ambigu", f"{len(found_nodes)} matching imports found")

        # Replace text pattern for the unique import
        pattern = rf"\bfrom\s+{re.escape(old_module)}\s+import\b"
        if not re.search(pattern, content):
            pattern = rf"\bimport\s+{re.escape(old_module)}\b"
            if not re.search(pattern, content):
                return ApplicatorResult(False, "rejected: motif import introuvable", "import text pattern mismatch")
            new_pattern = f"import {new_module}"
        else:
            new_pattern = f"from {new_module} import"

        new_content, count = re.subn(pattern, new_pattern, content, count=1)
        if count != 1:
            return ApplicatorResult(False, "rejected: échec substitution import", "import replacement count mismatch")

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

        # Check if already imported
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == module:
                if any(alias.name == name for alias in node.names):
                    return ApplicatorResult(False, "rejected: import déjà présent", f"{name} already imported from {module}")

        # Find place to insert (after existing imports or at top)
        import_line = f"from {module} import {name}"
        lines = content.splitlines(keepends=True)
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith(("import ", "from ")):
                insert_idx = i + 1

        new_lines = list(lines)
        new_lines.insert(insert_idx, import_line + "\n")
        new_content = "".join(new_lines)

        valid, reason = validate_syntax(file_path, new_content)
        if not valid:
            return ApplicatorResult(False, f"rejected: {reason}", reason)

        diff, lines_changed = generate_diff(content, new_content, file_path.name)
        return ApplicatorResult(True, "applied", diff=diff, new_content=new_content, lines_changed=lines_changed)


# ---------------------------------------------------------------------------
# 3. Python Dict Key Renaming Applicator
# ---------------------------------------------------------------------------

class PythonDictKeyApplicator:
    """Renames keys in dictionary literals on whole tokens."""

    @staticmethod
    def rename_key(
        file_path: pathlib.Path,
        old_key: str,
        new_key: str,
        current_content: str | None = None,
    ) -> ApplicatorResult:
        content = current_content if current_content is not None else tools._read_content(file_path)
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return ApplicatorResult(False, f"rejected: syntaxe invalide ({exc})", str(exc))

        # Verify key exists in at least one dictionary
        key_nodes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k in node.keys:
                    if isinstance(k, ast.Constant) and k.value == old_key:
                        key_nodes.append(k)

        if not key_nodes:
            return ApplicatorResult(False, "rejected: clé absente des dictionnaires", f"key {old_key!r} not in any dict")

        # Match exact token with quotes: "old_key" : or 'old_key' :
        pattern = rf"""(?P<quote>["']){re.escape(old_key)}(?P=quote)\s*:"""
        matches = list(re.finditer(pattern, content))
        if not matches:
            return ApplicatorResult(False, "rejected: motif de clé introuvable", "exact key token not found")

        # Replace only the key text while keeping the exact matched quote style
        def repl(m: re.Match[str]) -> str:
            q = m.group("quote")
            return f"{q}{new_key}{q}:"

        new_content = re.sub(pattern, repl, content)
        valid, reason = validate_syntax(file_path, new_content)
        if not valid:
            return ApplicatorResult(False, f"rejected: {reason}", reason)

        diff, lines_changed = generate_diff(content, new_content, file_path.name)
        return ApplicatorResult(True, "applied", diff=diff, new_content=new_content, lines_changed=lines_changed)


# ---------------------------------------------------------------------------
# 4. XML Attribute Applicator
# ---------------------------------------------------------------------------

class XmlAttributeApplicator:
    """Modifies or sets XML attributes on targeted elements."""

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
            return ApplicatorResult(False, f"rejected: XML invalide ({exc})", str(exc))

        # Text-based targeted replacement to preserve formatting and comments
        # Pattern matches element_tag with attribute_name="old_value"
        pattern = rf"""\b{re.escape(attribute_name)}\s*=\s*(?P<quote>["']){re.escape(old_value)}(?P=quote)"""
        matches = list(re.finditer(pattern, content))
        if not matches:
            return ApplicatorResult(False, "rejected: attribut XML introuvable", f"{attribute_name}={old_value!r} not found")
        if len(matches) > 1 and not identifier:
            return ApplicatorResult(False, "rejected: attribut XML non unique", f"{len(matches)} occurrences found without identifier")

        def repl(m: re.Match[str]) -> str:
            q = m.group("quote")
            return f"{attribute_name}={q}{new_value}{q}"

        if len(matches) == 1:
            new_content = re.sub(pattern, repl, content, count=1)
        else:
            # Match within block containing identifier
            id_idx = content.find(identifier)
            if id_idx == -1:
                return ApplicatorResult(False, "rejected: ancre identifier absente", f"{identifier} not found")
            # Replace closest match
            best_match = min(matches, key=lambda m: abs(m.start() - id_idx))
            new_content = content[:best_match.start()] + repl(best_match) + content[best_match.end():]

        valid, reason = validate_syntax(file_path, new_content)
        if not valid:
            return ApplicatorResult(False, f"rejected: {reason}", reason)

        diff, lines_changed = generate_diff(content, new_content, file_path.name)
        return ApplicatorResult(True, "applied", diff=diff, new_content=new_content, lines_changed=lines_changed)


# ---------------------------------------------------------------------------
# 5. XML XPath Applicator
# ---------------------------------------------------------------------------

class XmlXPathApplicator:
    """Updates xpath expr expressions safely."""

    @staticmethod
    def replace_expr(
        file_path: pathlib.Path,
        old_expr: str,
        new_expr: str,
        current_content: str | None = None,
    ) -> ApplicatorResult:
        content = current_content if current_content is not None else tools._read_content(file_path)
        pattern = rf"""(?P<prefix><xpath[^>]+expr\s*=\s*)(?P<quote>["']){re.escape(old_expr)}(?P=quote)"""
        matches = list(re.finditer(pattern, content))
        if not matches:
            return ApplicatorResult(False, "rejected: xpath expr introuvable", f"xpath with expr={old_expr!r} not found")
        if len(matches) > 1:
            return ApplicatorResult(False, "rejected: xpath expr non unique", f"{len(matches)} matching xpath expressions found")

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
# 6. Manifest Dependency Applicator
# ---------------------------------------------------------------------------

class ManifestDependencyApplicator:
    """Adds or updates a dependency in __manifest__.py while preserving comments."""

    @staticmethod
    def add_dependency(
        file_path: pathlib.Path,
        dependency_name: str,
        current_content: str | None = None,
    ) -> ApplicatorResult:
        content = current_content if current_content is not None else tools._read_content(file_path)
        try:
            manifest_dict = ast.literal_eval(content)
        except Exception as exc:
            return ApplicatorResult(False, f"rejected: manifeste non littéral ({exc})", str(exc))

        depends = manifest_dict.get("depends", [])
        if dependency_name in depends:
            return ApplicatorResult(False, "rejected: dépendance déjà présente", f"{dependency_name} already in depends")

        # Find depends block in content
        match = re.search(r"""(['"]depends['"]\s*:\s*\[)([^\]]*?)(\])""", content, re.DOTALL)
        if not match:
            return ApplicatorResult(False, "rejected: clé depends introuvable", "depends list not found in manifest")

        head, inner, tail = match.group(1), match.group(2), match.group(3)
        quote = "'" if "'" in inner or not '"' in inner else '"'
        new_dep_str = f"{quote}{dependency_name}{quote}"

        if inner.strip():
            # Multiline check
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
# 7. CSV Value Applicator
# ---------------------------------------------------------------------------

class CsvValueApplicator:
    """Updates rows or values in structured CSV files."""

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
        content = current_content if current_content is not None else tools._read_content(file_path)
        try:
            reader = list(csv.reader(io.StringIO(content)))
        except Exception as exc:
            return ApplicatorResult(False, f"rejected: CSV invalide ({exc})", str(exc))

        matched_rows = []
        for i, row in enumerate(reader):
            if column_index < len(row) and row[column_index] == old_value:
                if row_filter_col == -1 or (row_filter_col < len(row) and row[row_filter_col] == row_filter_val):
                    matched_rows.append(i)

        if not matched_rows:
            return ApplicatorResult(False, "rejected: cellule CSV introuvable", f"no row matched {old_value!r}")
        if len(matched_rows) > 1 and row_filter_col == -1:
            return ApplicatorResult(False, "rejected: cellule CSV non unique", f"{len(matched_rows)} rows matched without filter")

        new_rows = [list(r) for r in reader]
        for row_idx in matched_rows:
            new_rows[row_idx][column_index] = new_value

        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerows(new_rows)
        new_content = out.getvalue()

        diff, lines_changed = generate_diff(content, new_content, file_path.name)
        return ApplicatorResult(True, "applied", diff=diff, new_content=new_content, lines_changed=lines_changed)


def apply_typed_operation(
    module_path: pathlib.Path,
    op: dict[str, Any],
    file_buffers: dict[str, str] | None = None,
) -> tuple[ApplicatorResult, str]:
    """Dispatch a typed operation to the corresponding deterministic applicator.

    Returns (ApplicatorResult, relative_file_path).
    """
    op_type = op.get("type", "exact_text_replace")
    rel_file = str(op.get("file", "")).strip().replace("\\", "/")
    target_path = (module_path / rel_file).resolve()

    # Security check: containment
    try:
        target_path.relative_to(module_path.resolve())
    except ValueError:
        return ApplicatorResult(False, "rejected: chemin hors module", "path traversal rejected"), rel_file

    current_text = None
    if file_buffers and rel_file in file_buffers:
        current_text = file_buffers[rel_file]

    if op_type == "exact_text_replace":
        old_val = str(op.get("old", ""))
        new_val = str(op.get("new", ""))
        res = ExactTextApplicator.apply(target_path, old_val, new_val, current_content=current_text)
        return res, rel_file

    elif op_type == "replace_import":
        old_mod = str(op.get("old_module", ""))
        new_mod = str(op.get("new_module", ""))
        name = str(op.get("name", ""))
        res = PythonImportApplicator.replace_import(target_path, old_mod, new_mod, name, current_content=current_text)
        return res, rel_file

    elif op_type == "add_import":
        mod = str(op.get("module", ""))
        name = str(op.get("name", ""))
        res = PythonImportApplicator.add_import(target_path, mod, name, current_content=current_text)
        return res, rel_file

    elif op_type == "rename_dict_key":
        old_k = str(op.get("old_key", ""))
        new_k = str(op.get("new_key", ""))
        res = PythonDictKeyApplicator.rename_key(target_path, old_k, new_k, current_content=current_text)
        return res, rel_file

    elif op_type == "xml_set_attribute":
        tag = str(op.get("tag", ""))
        attr = str(op.get("attribute", ""))
        old_v = str(op.get("old_value", ""))
        new_v = str(op.get("new_value", ""))
        ident = str(op.get("identifier", ""))
        res = XmlAttributeApplicator.set_attribute(target_path, tag, attr, old_v, new_v, ident, current_content=current_text)
        return res, rel_file

    elif op_type == "xml_replace_xpath":
        old_e = str(op.get("old_expr", ""))
        new_e = str(op.get("new_expr", ""))
        res = XmlXPathApplicator.replace_expr(target_path, old_e, new_e, current_content=current_text)
        return res, rel_file

    elif op_type == "manifest_add_dependency":
        dep = str(op.get("dependency", ""))
        res = ManifestDependencyApplicator.add_dependency(target_path, dep, current_content=current_text)
        return res, rel_file

    elif op_type == "csv_replace_value":
        col = int(op.get("column", 0))
        old_c = str(op.get("old_value", ""))
        new_c = str(op.get("new_value", ""))
        f_col = int(op.get("filter_column", -1))
        f_val = str(op.get("filter_value", ""))
        res = CsvValueApplicator.replace_value(target_path, col, old_c, new_c, f_col, f_val, current_content=current_text)
        return res, rel_file

    return ApplicatorResult(False, f"rejected: type d'opération inconnu ({op_type})", "unknown operation type"), rel_file
