# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import importlib
import os
import pathlib
import pkgutil
import inspect

from .config import _AVAILABLE_MIGRATION_STEPS, _MANIFEST_NAMES
from .exception import ConfigException
from .log import logger
from .tools import _execute_shell, _get_latest_version_code
from .module_migration import ModuleMigration
from .base_migration_script import BaseMigrationScript


class Migration:
    def __init__(
        self,
        relative_directory_path,
        init_version_name,
        target_version_name,
        module_names=None,
        format_patch=False,
        remote_name="origin",
        commit_enabled=True,
        pre_commit=True,
        remove_migration_folder=True,
        no_oca_modules=False,
    ):
        if not module_names:
            module_names = []
        self._commit_enabled = commit_enabled
        self._pre_commit = pre_commit
        self._remove_migration_folder = remove_migration_folder
        self._no_oca_modules = no_oca_modules
        self._migration_steps = []
        self._migration_scripts = []
        self._module_migrations = []
        self._directory_path = False

        # Get migration steps
        found = False
        for item in _AVAILABLE_MIGRATION_STEPS:
            if not found and item["init_version_name"] != init_version_name:
                continue
            found = True
            self._migration_steps.append(item)
            if item["target_version_name"] == target_version_name:
                break

        if format_patch and len(module_names) != 1:
            raise ConfigException("Format patch option requires exactly one module")
        logger.debug(f"Module list: {module_names}")
        logger.debug(f"Format patch option: {format_patch}")

        if not os.path.exists(relative_directory_path):
            raise ConfigException(f"Directory not found: {relative_directory_path}")

        root_path = pathlib.Path(relative_directory_path)
        self._directory_path = pathlib.Path(root_path.resolve(strict=True))

        if format_patch:
            if not (root_path / module_names[0]).is_dir():
                self._get_code_from_previous_branch(module_names[0], remote_name)
            else:
                logger.warning(f"Ignoring format-patch, module {module_names[0]} already exists")

        if not module_names:
            child_paths = [x for x in root_path.iterdir() if x.is_dir()]
            for child_path in child_paths:
                if self._is_module_path(child_path):
                    if self._no_oca_modules and self._is_oca_module(child_path):
                        logger.info(f"Skipping OCA module '{child_path.name}' due to --no-oca-modules option")
                        continue
                    module_names.append(child_path.name)
        else:
            child_paths = [root_path / x for x in module_names]
            modules_to_remove = []
            for child_path in child_paths:
                if not self._is_module_path(child_path):
                    modules_to_remove.append(child_path.name)
                    logger.warning(f"No valid module found for '{child_path.name}' in '{root_path.resolve()}'")
                elif self._no_oca_modules and self._is_oca_module(child_path):
                    modules_to_remove.append(child_path.name)
                    logger.info(f"Skipping OCA module '{child_path.name}' due to --no-oca-modules option")
            for module_to_remove in modules_to_remove:
                module_names.remove(module_to_remove)

        if not module_names:
            raise ConfigException("No modules found to migrate. Exiting.")

        for module_name in module_names:
            self._module_migrations.append(ModuleMigration(self, module_name))

        if os.path.exists(".pre-commit-config.yaml") and self._pre_commit:
            self._run_pre_commit(module_names)

        # get migration scripts, depending to the migration list
        self._get_migration_scripts()

    def _run_pre_commit(self, module_names):
        logger.info("Run pre-commit")
        _execute_shell(
            "pre-commit run -a", path=self._directory_path, raise_error=False
        )
        if self._commit_enabled:
            logger.info("Stage and commit changes done by pre-commit")
            _execute_shell("git add -A", path=self._directory_path)
            _execute_shell(
                "git commit -m '[IMP] %s: pre-commit execution' --no-verify"
                % ", ".join(module_names),
                path=self._directory_path,
                raise_error=False,  # Don't fail if there is nothing to commit
            )

    def _is_module_path(self, module_path):
        return any([(module_path / x).exists() for x in _MANIFEST_NAMES])

    def _is_oca_module(self, module_path):
        """Check if a module is an OCA module."""
        for manifest_name in _MANIFEST_NAMES:
            manifest_path = module_path / manifest_name
            if manifest_path.exists():
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    manifest_data = eval(content)
                    if isinstance(manifest_data, dict):
                        author = manifest_data.get('author', '')
                        if 'Odoo Community Association (OCA)' in author:
                            return True
                    if 'Odoo Community Association (OCA)' in content:
                        return True
                except Exception:
                    pass
        return False

    def _get_code_from_previous_branch(self, module_name, remote_name):
        init_version = self._migration_steps[0]["init_version_name"]
        target_version = self._migration_steps[-1]["target_version_name"]
        branch_name = f"{target_version}-mig-{module_name}"

        logger.info(f"Creating new branch '{branch_name}' ...")
        _execute_shell(
            f"git checkout --no-track -b {branch_name} {remote_name}/{target_version}",
            path=self._directory_path
        )

        logger.info("Getting latest changes from old branch")
        _execute_shell(
            f"git fetch --depth 9999999 {remote_name} {init_version}",
            path=self._directory_path
        )

        _execute_shell(
            f"git format-patch --keep-subject --stdout {remote_name}/{target_version}..{remote_name}/{init_version} -- {module_name} | git am -3 --keep",
            path=self._directory_path
        )

    def _load_migration_script(self, full_name):
        module = importlib.import_module(full_name)
        result = [
            x[1]()
            for x in inspect.getmembers(module, inspect.isclass)
            if x[0] != "BaseMigrationScript" and issubclass(x[1], BaseMigrationScript)
        ]
        return result

    def _get_migration_scripts(self):
        self._migration_scripts.extend(
            self._load_migration_script("odoo_module_migrate.migration_scripts.migrate_allways")
        )
        if self._remove_migration_folder:
            self._migration_scripts.extend(
                self._load_migration_script("odoo_module_migrate.migration_scripts.migrate_remove_migration_folder")
            )
        
        all_packages = importlib.import_module("odoo_module_migrate.migration_scripts")
        migration_start = float(self._migration_steps[0]["init_version_code"])
        migration_end = float(self._migration_steps[-1]["target_version_code"])

        for loader, name, is_pkg in pkgutil.walk_packages(all_packages.__path__):
            if name in ("migrate_allways", "migrate_remove_migration_folder"):
                continue

            full_name = f"{all_packages.__name__}.{name}"
            real_name = name.replace("allways", _get_latest_version_code()) if "allways" in name else name
            splitted_name = real_name.split("_")

            script_start = float(splitted_name[1])
            script_end = float(splitted_name[2])

            if not (script_start >= migration_end or script_end <= migration_start):
                self._migration_scripts.extend(self._load_migration_script(full_name))

        scripts = [inspect.getfile(x.__class__).split("/")[-1] for x in self._migration_scripts]
        logger.debug(f"Migration scripts to execute:\n- " + "\n- ".join(scripts))

    def run(self):
        init_version = self._migration_steps[0]["init_version_name"]
        target_version = self._migration_steps[-1]["target_version_name"]
        logger.debug(f"Running migration from {init_version} to {target_version} in '{self._directory_path.resolve()}'")
        for module_migration in self._module_migrations:
            module_migration.run()
