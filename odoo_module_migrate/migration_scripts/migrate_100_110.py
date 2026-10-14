# Copyright (C) 2019 - Today: GRAP (http://www.grap.coop)
# @author: Sylvain LE GAL (https://twitter.com/legalsylvain)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo_module_migrate.base_migration_script import BaseMigrationScript

# Python 2 to 3 conversion is intentionally not attempted with the removed
# stdlib lib2to3 parser. Modern migrations (including 17 -> 20) already start
# from Python 3; a future legacy converter must use a maintained concrete-syntax
# parser and preserve Odoo source formatting.

# Modules: deprecated_modules/migrate_100_110/*.yaml


class MigrationScript(BaseMigrationScript):
    pass
