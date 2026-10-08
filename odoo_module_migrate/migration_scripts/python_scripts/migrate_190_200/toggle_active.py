"""Migrate the removed Odoo 20 ``toggle_active`` view buttons."""

import ast
import re

VIEW_RECORD_RE = re.compile(
    r"<record\b(?=[^>]*\bmodel\s*=\s*(['\"])ir\.ui\.view\1)[^>]*>[\s\S]*?</record>"
)
TAG_RE = re.compile(r'''<!--[\s\S]*?-->|<(?:[^>"']|"[^"]*"|'[^']*')+>''')


def _attribute(tag, name):
    return re.search(rf"\b{re.escape(name)}\s*=\s*(['\"])(.*?)\1", tag, re.DOTALL)


def _active_action(expression):
    try:
        node = ast.parse(expression.strip(), mode="eval").body
    except SyntaxError:
        return None
    if isinstance(node, ast.Name) and node.id == "active":
        return "action_unarchive"
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.Not)
        and isinstance(node.operand, ast.Name)
        and node.operand.id == "active"
    ):
        return "action_archive"
    return None


def _migrate_toggle_active_buttons(text):
    edits, unresolved = [], []
    for record in VIEW_RECORD_RE.finditer(text):
        for found in TAG_RE.finditer(record.group(0)):
            tag = found.group(0)
            if tag.startswith("<!--") or not re.match(r"<button\b", tag):
                continue
            button_type = _attribute(tag, "type")
            name = _attribute(tag, "name")
            if not (
                button_type
                and button_type.group(2) == "object"
                and name
                and name.group(2) == "toggle_active"
            ):
                continue
            invisible = _attribute(tag, "invisible")
            action = _active_action(invisible.group(2)) if invisible else None
            absolute_tag_start = record.start() + found.start()
            if action is None:
                unresolved.append(text.count("\n", 0, absolute_tag_start) + 1)
                continue
            start = absolute_tag_start + name.start(2)
            edits.append((start, start + len(name.group(2)), action))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text, unresolved


def migrate_toggle_active_buttons(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".xml",)):
        text = tools._read_content(path)
        if "toggle_active" not in text:
            continue
        new, unresolved = _migrate_toggle_active_buttons(text)
        if new != text:
            tools._write_content(path, new)
            logger.info(
                "[20] Replaced unambiguous toggle_active view buttons. File %s", path
            )
        for line in unresolved:
            logger.error(
                "[20] toggle_active() was removed; choose action_archive or "
                "action_unarchive for this button. File %s:%s",
                path,
                line,
            )
