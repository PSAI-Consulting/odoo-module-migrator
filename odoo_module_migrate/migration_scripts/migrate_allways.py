# Copyright (C) 2019 - Today: GRAP (http://www.grap.coop)
# @author: Sylvain LE GAL (https://twitter.com/legalsylvain)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo_module_migrate.base_migration_script import BaseMigrationScript

_TEXT_REPLACES = {
    ".xml": {
        r"<data +noupdate=\"0\" *>": "<data>",
    }
}


def set_module_installable(**kwargs):
    """'installable': False -> True with --set-installable (OCA workflow:
    modules are disabled on the new branch until migrated). Otherwise the
    module was probably disabled on purpose (abandoned): left as is."""
    tools = kwargs["tools"]
    manifest_path = kwargs["manifest_path"]
    old_term = r"('|\")installable('|\").*(False)"
    if not tools.RUN_CONTEXT.get("set_installable", True):
        import re

        text = tools._read_content(manifest_path)
        match = re.search(old_term, text)
        if match:
            line = text.count("\n", 0, match.start()) + 1
            kwargs["logger"].warning(
                "The module is not installable ('installable': False): left as is, use"
                " --set-installable to enable it. File %s:%s" % (manifest_path, line)
            )
        return
    new_term = r"\1installable\2: True"
    tools._replace_in_file(
        manifest_path, {old_term: new_term}, "Set module installable"
    )


class MigrationScript(BaseMigrationScript):
    _TEXT_REPLACES = _TEXT_REPLACES
    _GLOBAL_FUNCTIONS = [
        set_module_installable,
    ]
