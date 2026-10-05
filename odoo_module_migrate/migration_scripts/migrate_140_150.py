# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import ast
import re

from odoo_module_migrate.base_migration_script import BaseMigrationScript

# Source: odoo 15.0, assets are declared in the manifest 'assets' key
# https://www.odoo.com/documentation/15.0/developer/reference/frontend/assets.html
_ASSET_TEMPLATE_RE = re.compile(
    r"""<template\b[^>]*\binherit_id=["'](web\.assets_\w+|web\._assets_\w+|point_of_sale\.assets)["']"""
)


def check_assets_declaration(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    """Warn only when the module really uses the pre-15.0 asset declarations."""
    try:
        manifest = ast.literal_eval(tools._read_content(manifest_path))
    except (ValueError, SyntaxError):
        manifest = {}
    for key in ("qweb", "css", "js"):
        if manifest.get(key):
            logger.warning(
                "[15] Manifest key '%s' is not supported anymore: move these files"
                " to the 'assets' key. File %s" % (key, manifest_path)
            )
    for xml_file in tools.get_files(module_path, (".xml",)):
        content = tools._read_content(xml_file)
        for match in _ASSET_TEMPLATE_RE.finditer(content):
            line = content.count("\n", 0, match.start()) + 1
            logger.warning(
                "[15] Assets bundle '%s' extended in XML: move the files to the"
                " manifest 'assets' key. File %s:%s" % (match.group(1), xml_file, line)
            )


class MigrationScript(BaseMigrationScript):
    _GLOBAL_FUNCTIONS = [check_assets_declaration]
