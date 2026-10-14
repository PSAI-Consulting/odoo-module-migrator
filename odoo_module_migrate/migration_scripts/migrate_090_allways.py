# Copyright (C) 2019 - Today: GRAP (http://www.grap.coop)
# @author: Sylvain LE GAL (https://twitter.com/legalsylvain)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
# Odoo 10.0: namespace odoo (9.0 still uses openerp) and __manifest__.py
# (9.0: __openerp__.py), so from the 9.0 -> 10.0 step on (formerly migrate_080_allways).

from odoo_module_migrate.base_migration_script import BaseMigrationScript

_FILE_RENAMES = {"__openerp__.py": "__manifest__.py"}


class MigrationScript(BaseMigrationScript):

    _FILE_RENAMES = _FILE_RENAMES
