"""Model._table_query was removed in 20.0 (odoo 7809101d2dec '[IMP] orm:
remove Model._table_query'): report models override the ``_table_sql``
property instead.

In 19.0 the ORM turned ``_table_query`` into the table expression itself
(odoo/orm/models.py ``_table_sql``): an ``SQL`` object became
``SQL("(%s)", query)``, a string ``SQL(f"({query})")``. A ``@property`` named
``_table_query`` is renamed ``_table_sql`` and each of its ``return`` values is
wrapped the same way, so the query is unchanged. Other forms (class attribute,
reads of ``self._table_query``) stay reported by text_errors.
"""

import ast
import re

from odoo_module_migrate.analysis.fields import _Positions

_SQL_IMPORT_RE = re.compile(r"^from odoo\.tools import (?P<names>[^\n(]+)$", re.MULTILINE)
_ODOO_IMPORT_RE = re.compile(r"^from odoo import [^\n]+$", re.MULTILINE)


def _ensure_sql_import(text):
    match = _SQL_IMPORT_RE.search(text)
    if match:
        names = [name.strip() for name in match["names"].split(",")]
        if "SQL" in names:
            return text
        return text[:match.start("names")] + ", ".join(sorted([*names, "SQL"])) + text[match.end("names"):]
    match = _ODOO_IMPORT_RE.search(text)
    position = match.end() + 1 if match else 0
    return text[:position] + "from odoo.tools import SQL\n" + text[position:]


def _convert(text):
    """(new text, number of converted properties)."""
    tree = ast.parse(text)
    pos = _Positions(text)
    edits = []
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        for function in cls.body:
            if not (
                isinstance(function, ast.FunctionDef)
                and function.name == "_table_query"
                and any(isinstance(d, ast.Name) and d.id == "property" for d in function.decorator_list)
            ):
                continue
            returns = [node for node in ast.walk(function) if isinstance(node, ast.Return) and node.value]
            if not returns:
                continue
            name_start = pos.offset(function.lineno, function.col_offset)
            name_at = text.index("_table_query", name_start)
            edits.append((name_at, name_at + len("_table_query"), "_table_sql"))
            for node in returns:
                start = pos.offset(node.lineno, node.col_offset)
                end = pos.offset(node.end_lineno, node.end_col_offset)
                indent = " " * node.col_offset
                expression = text[pos.offset(node.value.lineno, node.value.col_offset):end]
                edits.append((start, end, (
                    f"query = {expression}\n"
                    f'{indent}return SQL("(%s)", query) if isinstance(query, SQL) else SQL(f"({{query}})")'
                )))
    if not edits:
        return text, 0
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return _ensure_sql_import(text), sum(1 for edit in edits if edit[2] == "_table_sql")


def migrate_table_query(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py",)):
        text = tools._read_content(path)
        if "_table_query" not in text:
            continue
        try:
            new, count = _convert(text)
        except SyntaxError:
            continue
        if count:
            tools._write_content(path, new)
            logger.info(
                "[20] _table_query property converted to _table_sql, same query as the 19.0 ORM built "
                "(odoo 7809101d2dec '[IMP] orm: remove Model._table_query'). File %s",
                path,
            )
