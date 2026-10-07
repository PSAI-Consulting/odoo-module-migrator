"""Odoo 19: env shortcuts and UoM precision (odoo 8fd73ea390ba)."""

import ast
import re
from odoo_module_migrate.analysis.fields import (
    _Positions,
    python_usages as _python_usages,
)


def migrate_compatibility(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py", ".xml")):
        text = tools._read_content(path)
        new = text
        if path.suffix == ".xml":
            # Match only the digits attribute, not labels or translated text.
            new = re.sub(
                r"""<!--[\s\S]*?-->|(\bdigits\s*=\s*(["']))Product Unit of Measure(\2)""",
                lambda m: (
                    m[0] if m[0].startswith("<!--") else m[1] + "Product Unit" + m[3]
                ),
                text,
            )
        else:
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            pos, edits = _Positions(text), {}
            usages, _ = _python_usages(text)
            for usage in usages:
                if usage.field in {
                    "_context",
                    "_cr",
                    "_uid",
                } and usage.context.endswith("." + usage.field):
                    edits[usage.start, usage.end] = "env." + usage.field[1:]
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.keyword)
                    and node.arg == "digits"
                    and isinstance(node.value, ast.Constant)
                    and node.value.value == "Product Unit of Measure"
                ):
                    value = node.value
                    start, end = (
                        pos.offset(value.lineno, value.col_offset),
                        pos.offset(value.end_lineno, value.end_col_offset),
                    )
                    edits[start, end] = text[start:end].replace(
                        "Product Unit of Measure", "Product Unit"
                    )
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "ref"
                    and node.args
                ):
                    arg = node.args[0]
                    if (
                        isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                        and arg.value.startswith("uom.uom_categ_")
                    ):
                        logger.error(
                            "[19] UoM categories removed; compare reference units using _has_common_reference(other_uom) (addons/uom/models/uom_uom.py). File %s:%s",
                            path,
                            node.lineno,
                        )
            for (start, end), replacement in sorted(edits.items(), reverse=True):
                new = new[:start] + replacement + new[end:]
        if new != text:
            tools._write_content(path, new)
            logger.info(
                "[19] Migrated env shortcuts / UoM decimal precision (odoo 8fd73ea390ba; odoo/orm/models.py). File %s",
                path,
            )
