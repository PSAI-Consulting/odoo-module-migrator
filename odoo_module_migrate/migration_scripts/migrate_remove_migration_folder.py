# Copyright (C) 2019 - Today: GRAP (http://www.grap.coop)
# @author: Sylvain LE GAL (https://twitter.com/legalsylvain)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import os
import shutil
from odoo_module_migrate.base_migration_script import BaseMigrationScript


def remove_migration_folder(**kwargs):
    logger = kwargs["logger"]
    module_path = kwargs["module_path"]
    migration_path_folder = os.path.join(module_path, "migrations")
    if os.path.exists(migration_path_folder):
        logger.info("Removing 'migrations' folder")
        shutil.rmtree(migration_path_folder)


class MigrationScript(BaseMigrationScript):
    _GLOBAL_FUNCTIONS = [
        remove_migration_folder,
    ]
