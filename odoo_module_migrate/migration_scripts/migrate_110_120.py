# Copyright (C) 2019 - Today: GRAP (http://www.grap.coop)
# @author: Sylvain LE GAL (https://twitter.com/legalsylvain)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo_module_migrate.base_migration_script import BaseMigrationScript

_TEXT_REPLACES = {
    ".py": {
        "from odoo.addons.base.res": "from odoo.addons.base.models",
        "from odoo.addons.base.ir": "from odoo.addons.base.models",
    }
}

_TEXT_WARNINGS = {
    ".xml": {
        r"<label\b(?![^>]*\bfor\s*=)[^>]*>": (
            '[V12] A <label> in a view has no for="..." attribute'
        ),
        r"<filter\b(?![^>]*\bname\s*=)[^>]*>": (
            '[V12] A <filter> in a search view has no name="..." attribute'
        ),
        r"(?s)<tree\b[^>]*>(?:(?!</tree>).)*?<button\b(?![^>]*\bstring\s*=)[^>]*>": (
            '[V12] A <button> in a tree view has no string="..." attribute for accessibility'
        ),
    }
}

# Modules: deprecated_modules/migrate_110_120/*.yaml


class MigrationScript(BaseMigrationScript):
    _TEXT_REPLACES = _TEXT_REPLACES
    _TEXT_WARNINGS = _TEXT_WARNINGS
