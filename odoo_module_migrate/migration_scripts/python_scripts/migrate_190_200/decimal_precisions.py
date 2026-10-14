"""Decimal precision renamed in 19.0, still found in modules said to be 19.0.

'Product Unit of Measure' is 'Product Unit' from 19.0 (odoo 8fd73ea390ba,
uom/data/uom_data.xml, same xmlid uom.decimal_product_uom). The 18 -> 19 step
converts it; a module already marked 19.0 that kept the old name (OCA
stock_available) only goes through 19 -> 20, where the name is unknown and
Odoo silently falls back to its default precision.
"""

import ast

from odoo_module_migrate.analysis.fields import _Positions
from odoo_module_migrate.migration_scripts.python_scripts.migrate_180_190.compatibility import (
    _precision_python_edits,
    _rename_precision_xml,
)


def migrate_renamed_decimal_precisions(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py", ".xml")):
        text = tools._read_content(path)
        if "Product Unit of Measure" not in text:
            continue
        if path.suffix == ".xml":
            new = _rename_precision_xml(text)
        else:
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            pos, edits, new = _Positions(text), {}, text
            for node in ast.walk(tree):
                edits.update(_precision_python_edits(node, text, pos))
            for (start, end), replacement in sorted(edits.items(), reverse=True):
                new = new[:start] + replacement + new[end:]
        if new != text:
            tools._write_content(path, new)
            logger.info(
                "[19] Decimal precision 'Product Unit of Measure' renamed 'Product Unit' "
                "(odoo 8fd73ea390ba, uom/data/uom_data.xml). File %s",
                path,
            )
