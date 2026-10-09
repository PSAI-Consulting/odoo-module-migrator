"""Complete ``purchase.order.notes`` -> ``note`` in ambiguous expressions.

Odoo commit bc24cdddbec5 renamed the field. The model-aware rule handles
ordinary views and resolved recordsets; this pass covers purchase report QWeb
variables and clearly named parameters inside purchase.order extensions.
"""

import ast
import re

from odoo_module_migrate.analysis import fields


PURCHASE_REPORT_RE = re.compile(
    r"\bpurchase\.report_purchase(?:order|quotation)_document\b"
)
TAG_RE = re.compile(r'<!--[\s\S]*?-->|<[^>"\']*(?:"[^"]*"|\'[^\']*\'|[^>"\']*)*>')
QWEB_NOTES_RE = re.compile(r"\b(o|purchase_order|order)\.notes\b")
PYTHON_RECEIVERS = {"self", "purchase_order", "order", "po"}


def _python_edits(text):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    positions = fields._Positions(text)
    edits = []
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef) or "purchase.order" not in fields._class_models(cls):
            continue
        for node in ast.walk(cls):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "notes"
                and isinstance(node.value, ast.Name)
                and node.value.id in PYTHON_RECEIVERS
            ):
                end = positions.offset(node.end_lineno, node.end_col_offset)
                edits.append((end - len("notes"), end, node.lineno))
    return edits


def migrate_purchase_order_note(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py", ".xml")):
        text = tools._read_content(path)
        if "notes" not in text:
            continue
        if path.suffix == ".py":
            edits = _python_edits(text)
            new = text
            for start, end, _line in sorted(edits, reverse=True):
                new = new[:start] + "note" + new[end:]
        elif PURCHASE_REPORT_RE.search(text):
            changed_lines = []

            def replace_tag(match):
                tag = match.group(0)
                if tag.startswith("<!--"):
                    return tag

                def replace_field(found):
                    changed_lines.append(text.count("\n", 0, match.start()) + 1)
                    return found.group(1) + ".note"

                return QWEB_NOTES_RE.sub(replace_field, tag)

            new = TAG_RE.sub(replace_tag, text)
            edits = [(0, 0, line) for line in changed_lines]
        else:
            continue
        if new == text:
            continue
        tools._write_content(path, new)
        for _start, _end, line in edits:
            logger.info(
                "Renamed purchase.order.notes to note (odoo bc24cdddbec5). "
                "File %s:%s",
                path,
                line,
            )
