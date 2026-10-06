# Copyright (C) 2019 - Today: GRAP (http://www.grap.coop)
# @author: Sylvain LE GAL (https://twitter.com/legalsylvain)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo_module_migrate.base_migration_script import BaseMigrationScript

# TODO
# All <label> elements in views must have a for="" attribute.
# All <filter> elements in search views must have a name attribute.
# All <button> elements in a tree view should have a string attribute
#   for accessibility.

_TEXT_REPLACES = {
    ".py": {
        "from odoo.addons.base.res": "from odoo.addons.base.models",
        "from odoo.addons.base.ir": "from odoo.addons.base.models",
    }
}

# Modules: deprecated_modules/migrate_110_120/*.yaml


class MigrationScript(BaseMigrationScript):
    _TEXT_REPLACES = _TEXT_REPLACES
