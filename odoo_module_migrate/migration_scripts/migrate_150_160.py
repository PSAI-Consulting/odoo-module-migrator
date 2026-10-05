# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo_module_migrate.base_migration_script import BaseMigrationScript
from odoo_module_migrate.log import logger

def log_migration_start(logger, module_path, module_name, manifest_path, migration_steps, tools):
    logger.info(f"Starting migration from 15.0 to 16.0 for {module_name}")

class MigrationScript(BaseMigrationScript):
    _GLOBAL_FUNCTIONS = [log_migration_start]
