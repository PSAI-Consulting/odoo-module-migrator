# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""odoo.models is a package since 19.0 and re-exports much less.

Source: 18.0 odoo/models.py vs 19.0 odoo/models/__init__.py (top level names):
``api``, ``fields`` and ``tools`` cannot be imported from ``odoo.models``
anymore; they are subpackages of ``odoo`` (``from odoo import api``).

    from odoo.models import Model, api   ->   from odoo import api
                                               from odoo.models import Model

Other names that ``odoo.models`` does not export anymore (AccessError,
Command, SUPERUSER_ID...) are reported.
"""

import ast

MOVED_TO_ODOO = {"api", "fields", "tools"}
# names of 18.0 odoo.models still exported by 19.0 odoo/models/__init__.py are
# fine; these frequently imported ones are not anymore
NOT_EXPORTED = {
    "AccessError", "MissingError", "UserError", "ValidationError", "Command", "SUPERUSER_ID",
    # (Query is not here: exported again by 20.0 odoo/models/__init__.py)
    "NewId", "SQL", "OrderedSet", "LastOrderedSet", "LRU", "Datetime", "Field",
    "DEFAULT_SERVER_DATE_FORMAT", "DEFAULT_SERVER_DATETIME_FORMAT",
}


def _offsets(text):
    lines = text.splitlines(keepends=True)
    starts = [0, 0]
    for line in lines:
        starts.append(starts[-1] + len(line))

    def offset(lineno, col):
        return starts[lineno] + len(lines[lineno - 1].encode("utf-8")[:col].decode("utf-8", "replace"))

    return offset


def _rewrite(text):
    """Return (new text, [(line, name)] not exported anymore)."""
    tree = ast.parse(text)
    offset = _offsets(text)
    edits, reported = [], []
    for node in tree.body:
        if not (isinstance(node, ast.ImportFrom) and node.module == "odoo.models" and node.level == 0):
            continue
        moved = [a for a in node.names if a.name in MOVED_TO_ODOO]
        reported += [(node.lineno, a.name) for a in node.names if a.name in NOT_EXPORTED]
        if not moved:
            continue
        kept = [a for a in node.names if a.name not in MOVED_TO_ODOO]

        def fmt(aliases):
            return ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in aliases)

        start = offset(node.lineno, node.col_offset)
        end = offset(node.end_lineno, node.end_col_offset)
        indent = text[text.rfind("\n", 0, start) + 1:start]
        new = f"from odoo import {fmt(moved)}"
        if kept:
            new += f"\n{indent}from odoo.models import {fmt(kept)}"
        edits.append((start, end, new))
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    return text, reported


def migrate_odoo_models_imports(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py",)):
        text = tools._read_content(path)
        if "odoo.models import" not in text:
            continue
        try:
            new, reported = _rewrite(text)
        except SyntaxError:
            continue
        if new != text:
            tools._write_content(path, new)
            logger.info("[19] api / fields / tools imported from odoo instead of odoo.models in %s" % path)
        for line, name in reported:
            logger.error(
                "[19] '%s' cannot be imported from odoo.models anymore (19.0 odoo/models/__init__.py):"
                " import it from its own module (odoo.exceptions, odoo.fields, odoo.api...). File %s:%s"
                % (name, path, line)
            )
