# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo_module_migrate.base_migration_script import BaseMigrationScript
from odoo_module_migrate.log import logger

def log_migration_start(logger, module_path, module_name, manifest_path, migration_steps, tools):
    logger.info(f"Starting migration from 14.0 to 15.0 for {module_name}")
    logger.warning("Migration from 14.0 to 15.0 involves significant asset changes (Moving assets to __manifest__.py). Please verify manually.")

class MigrationScript(BaseMigrationScript):
    _GLOBAL_FUNCTIONS = [log_migration_start]
