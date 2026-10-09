# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Migrate simple Odoo 19 SQL report extension hooks to TableSQL."""

import ast
import re

from odoo_module_migrate.analysis import fields


def _super_assignment(function, method):
    if not function.body or not isinstance(function.body[0], ast.Assign):
        return None
    assignment = function.body[0]
    if len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name):
        return None
    call = assignment.value
    if not (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == method
        and isinstance(call.func.value, ast.Call)
        and isinstance(call.func.value.func, ast.Name)
        and call.func.value.func.id == "super"
        and not call.args
        and not call.keywords
    ):
        return None
    return assignment.targets[0].id


def _table_expression(value, aliases):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", value.strip()):
        return None
    root, _, tail = value.strip().partition(".")
    base = aliases.get(root)
    return base + "." + tail if base else None


def _sale_select(function):
    variable = _super_assignment(function, "_select_additional_fields")
    if not variable or len(function.body) < 3:
        return None
    values = []
    for statement in function.body[1:-1]:
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Subscript)
            and isinstance(statement.targets[0].value, ast.Name)
            and statement.targets[0].value.id == variable
            and isinstance(statement.targets[0].slice, ast.Constant)
            and isinstance(statement.targets[0].slice.value, str)
            and isinstance(statement.value, ast.Constant)
        ):
            return None
        expression = _table_expression(
            statement.value.value, {"s": "table.order_id", "l": "table"}
        )
        if not expression:
            return None
        values.append((statement.targets[0].slice.value, expression))
    returned = function.body[-1]
    if not (
        isinstance(returned, ast.Return)
        and isinstance(returned.value, ast.Name)
        and returned.value.id == variable
        and values
    ):
        return None
    indent = " " * function.col_offset
    inner = indent + "    "
    mapping = "\n".join(
        f'{inner}    "{name}": {expression},' for name, expression in values
    )
    return (
        "def _select_dict(self, table):\n"
        f"{inner}return super()._select_dict(table) | {{\n{mapping}\n{inner}}}"
    )


def _sale_groupby(function):
    variable = _super_assignment(function, "_group_by_sale")
    if not variable or len(function.body) != 3:
        return None
    addition, returned = function.body[1:]
    if not (
        isinstance(addition, ast.AugAssign)
        and isinstance(addition.target, ast.Name)
        and addition.target.id == variable
        and isinstance(addition.op, ast.Add)
        and isinstance(addition.value, ast.Constant)
        and isinstance(addition.value.value, str)
        and isinstance(returned, ast.Return)
        and isinstance(returned.value, ast.Name)
        and returned.value.id == variable
    ):
        return None
    expressions = []
    for value in addition.value.value.strip().lstrip(",").split(","):
        expression = _table_expression(
            value.strip(), {"s": "table.order_id", "l": "table"}
        )
        if not expression:
            return None
        expressions.append(expression)
    if not expressions:
        return None
    indent = " " * function.col_offset
    inner = indent + "    "
    return (
        "def _groupby_list(self, table):\n"
        f"{inner}return super()._groupby_list(table) + [{', '.join(expressions)}]"
    )


def _account_select(function):
    variable = _super_assignment(function, "_select")
    if not variable or len(function.body) != 3:
        return None
    addition, returned = function.body[1:]
    if not (
        isinstance(addition, ast.AugAssign)
        and isinstance(addition.target, ast.Name)
        and addition.target.id == variable
        and isinstance(addition.op, ast.Add)
        and isinstance(addition.value, ast.Constant)
        and isinstance(addition.value.value, str)
        and isinstance(returned, ast.Return)
        and isinstance(returned.value, ast.Name)
        and returned.value.id == variable
    ):
        return None
    sql = " ".join(addition.value.value.split()).lstrip(", ")
    columns = []
    for part in sql.split(","):
        match = re.fullmatch(
            r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\s+(?:as\s+)?([A-Za-z_]\w*)",
            part.strip(),
            re.IGNORECASE,
        )
        if not match:
            return None
        expression = _table_expression(
            match.group(1), {"move": "table.move_id", "line": "table"}
        )
        if not expression:
            return None
        columns.append((match.group(2), expression))
    if not columns:
        return None
    indent = " " * function.col_offset
    inner = indent + "    "
    items = "\n".join(
        f'{inner}    SQL("%s AS {name}", {expression}),' for name, expression in columns
    )
    return (
        "def _select_list(self, table):\n"
        f"{inner}return [\n{inner}    *super()._select_list(table),\n"
        f"{items}\n{inner}]"
    )


def _add_sql_import(text):
    if re.search(r"(?m)^from odoo\.tools import .*\bSQL\b", text):
        return text
    tree = ast.parse(text)
    position = 0
    for statement in tree.body:
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            position = statement.end_lineno
        elif position:
            break
    lines = text.splitlines(keepends=True)
    lines.insert(position, "from odoo.tools import SQL\n")
    return "".join(lines)


def migrate_report_table_sql(module_path, tools, logger, **kwargs):
    for path in tools.get_files(module_path, (".py",)):
        text = tools._read_content(path)
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        positions = fields._Positions(text)
        edits = []
        needs_sql = False
        for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            model_names = fields._class_models(cls)
            if not model_names:
                continue
            model = model_names[0]
            for function in cls.body:
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                replacement = None
                if model == "sale.report" and function.name == "_select_additional_fields":
                    replacement = _sale_select(function)
                elif model == "sale.report" and function.name == "_group_by_sale":
                    replacement = _sale_groupby(function)
                elif model == "account.invoice.report" and function.name == "_select":
                    replacement = _account_select(function)
                    needs_sql |= replacement is not None
                if replacement:
                    edits.append(
                        (
                            positions.offset(function.lineno, function.col_offset),
                            positions.offset(function.end_lineno, function.end_col_offset),
                            replacement,
                            function.name,
                            replacement.split("(", 1)[0].split()[-1],
                            function.lineno,
                        )
                    )
        for start, end, replacement, _old, _new, _line in sorted(edits, reverse=True):
            text = text[:start] + replacement + text[end:]
        if needs_sql:
            text = _add_sql_import(text)
        if edits:
            tools._write_content(path, text)
            for _start, _end, _replacement, old, new, line in edits:
                logger.info(
                    "Migrated Odoo 20 TableSQL report hook %s to %s. File %s:%s",
                    old,
                    new,
                    path,
                    line,
                )
