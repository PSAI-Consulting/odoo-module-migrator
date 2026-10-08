"""Prepare translated legacy SQL constraints for Odoo's official converter.

The official 18.1 converter evaluates ``_sql_constraints`` with
``ast.literal_eval``.  A conventional ``_("message")`` therefore raises a
``ValueError`` and leaves the constraint behind.  ``models.Constraint``
translates its message itself, so removing this one redundant wrapper keeps
the behavior and lets the official script finish.
"""

import ast
import json

from odoo_module_migrate.analysis.fields import _Positions


def _is_sql_constraints_assignment(node):
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return any(
        isinstance(target, (ast.Name, ast.Attribute))
        and (target.id if isinstance(target, ast.Name) else target.attr)
        == "_sql_constraints"
        for target in targets
    )


def _translated_literal(node):
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return None
    return json.dumps(node.args[0].value, ensure_ascii=False)


def _unwrap_translated_constraint_messages(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return text
    positions = _Positions(text)
    edits = []
    for assignment in ast.walk(tree):
        if not isinstance(assignment, (ast.Assign, ast.AnnAssign)):
            continue
        if not _is_sql_constraints_assignment(assignment):
            continue
        value = assignment.value
        if not isinstance(value, (ast.List, ast.Tuple)):
            continue
        for constraint in value.elts:
            if (
                not isinstance(constraint, (ast.List, ast.Tuple))
                or len(constraint.elts) < 3
            ):
                continue
            message = constraint.elts[2]
            replacement = _translated_literal(message)
            if replacement is None:
                continue
            edits.append(
                (
                    positions.offset(message.lineno, message.col_offset),
                    positions.offset(message.end_lineno, message.end_col_offset),
                    replacement,
                )
            )
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text
