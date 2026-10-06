# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import importlib
import os
import pathlib
import pkgutil
import inspect
import ast
import subprocess
import traceback

from .config import _AVAILABLE_MIGRATION_STEPS, _MANIFEST_NAMES
from .exception import ConfigException
from .log import logger
from . import report, tools
from .tools import _run, _get_latest_version_code
from .upgrade_code import run_upgrade_code
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
        upgrade_code_options=None,
        dry_run=False,
        write_report=True,
        set_installable=False,
        report_dir=None,
    ):
        if not module_names:
            module_names = []
        self._commit_enabled = commit_enabled
        self._pre_commit = pre_commit
        self._remove_migration_folder = remove_migration_folder
        self._no_oca_modules = no_oca_modules
        self._upgrade_code_options = upgrade_code_options
        self._dry_run = dry_run
        self.upgrade_code_result = None
        self._report = write_report
        self._set_installable = set_installable
        self._report_dir = pathlib.Path(report_dir).resolve() if report_dir else None
        self.report_collector = None
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

        if self._has_pre_commit_config():
            self._run_pre_commit(module_names)

        # get migration scripts, depending to the migration list
        self._get_migration_scripts()

    def _has_pre_commit_config(self):
        return (
            self._pre_commit
            and (self._directory_path / ".pre-commit-config.yaml").exists()
        )

    def _run_pre_commit_if_configured(self):
        if not self._has_pre_commit_config():
            return
        try:
            _run(["pre-commit", "run", "-a"], path=self._directory_path, check=False)
        except FileNotFoundError:
            logger.warning("pre-commit is not installed: skipping it")

    def _run_pre_commit(self, module_names):
        logger.info("Run pre-commit")
        self._run_pre_commit_if_configured()
        if self._commit_enabled:
            logger.info("Stage and commit changes done by pre-commit")
            _run(["git", "add", "-A"], path=self._directory_path)
            # Don't fail if there is nothing to commit
            _run(
                [
                    "git", "commit", "--no-verify", "-m",
                    "[IMP] %s: pre-commit execution" % ", ".join(module_names),
                ],
                path=self._directory_path,
                check=False,
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
                    manifest_data = ast.literal_eval(content)
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
        _run(
            ["git", "checkout", "--no-track", "-b", branch_name,
             f"{remote_name}/{target_version}"],
            path=self._directory_path,
        )

        logger.info("Getting latest changes from old branch")
        _run(
            ["git", "fetch", "--depth", "9999999", remote_name, init_version],
            path=self._directory_path,
        )

        patch = _run(
            ["git", "format-patch", "--keep-subject", "--stdout",
             f"{remote_name}/{target_version}..{remote_name}/{init_version}",
             "--", module_name],
            path=self._directory_path,
        )
        subprocess.run(
            ["git", "am", "-3", "--keep"], input=patch,
            cwd=str(self._directory_path), check=True,
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
        # Rules of the migrator itself, then the official scripts of the
        # target Odoo on all the modules at once, then format / commit
        tools.RUN_CONTEXT["upgrade_code"] = bool(self._upgrade_code_options)
        tools.RUN_CONTEXT["set_installable"] = self._set_installable
        if self._report:
            self.report_collector = report.ReportCollector(
                [(m._module_name, m._module_path) for m in self._module_migrations]
            )
            logger.addHandler(self.report_collector)
        try:
            for module_migration in self._module_migrations:
                module_migration.apply_scripts()
            if self.report_collector:
                self.report_collector.current = None
            if self._upgrade_code_options:
                for step in (self._run_upgrade_code, self._check_view_anchors):
                    try:
                        step()
                    except Exception as e:  # noqa: BLE001 - reported, the rest goes on
                        logger.error("%s failed: %s: %s" % (step.__name__, type(e).__name__, e))
                        logger.debug(traceback.format_exc())
            if float(init_version) < 20 <= float(target_version):
                self._check_access_records_left()
            for module_migration in self._module_migrations:
                module_migration.restore()
            if self.report_collector:
                self._write_reports(init_version, target_version)
            for module_migration in self._module_migrations:
                module_migration.commit()
        finally:
            tools.RUN_CONTEXT.clear()
            if self.report_collector:
                logger.removeHandler(self.report_collector)

    def _write_reports(self, init_version, target_version):
        reports = []
        for module_migration in self._module_migrations:
            module_report = self.report_collector.reports[module_migration._module_name]
            changes = module_migration.changed_files(ignore={report.REPORT_NAME})
            content = report.render(module_report, init_version, target_version, changes)
            if self._report_dir:
                path = self._report_dir / f"{module_migration._module_name}.md"
            else:
                path = module_migration._module_path / report.REPORT_NAME
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            reports.append(module_report)
            logger.info(
                "[%s] report: %s (risk: %s, %d TODO)"
                % (module_migration._module_name, path, module_report.risk, len(module_report.todos))
            )
        if self._report_dir:
            (self._report_dir / "README.md").write_text(
                report.render_summary(reports, init_version, target_version), encoding="utf-8"
            )

    def _check_access_records_left(self):
        """ir.rule / ir.model.access left in XML once converted (by Odoo's
        19.4-00-ir-access.py or by the fallback of migrate_190_200)."""
        from .upgrade_code.prepare import ACCESS_LEFT_MESSAGE, access_records_left

        for module_migration in self._module_migrations:
            for path, line in access_records_left(module_migration._module_path):
                logger.warning("%s. File %s:%s" % (ACCESS_LEFT_MESSAGE, path, line))

    def _check_view_anchors(self):
        """Inherited views anchored on fields absent from the target views."""
        from .analysis import views

        options = self._upgrade_code_options
        reference = list(options.addons_path)
        logger.info("Checking the view anchors against the target Odoo views...")
        index = views.ViewIndex.build(
            reference + list(options.context_path) + [self._directory_path]
        )
        reference_modules = {m.name for m in views._module_dirs(reference)}
        for module_migration in self._module_migrations:
            unknown = index.unknown_dependencies(module_migration._module_name)
            if unknown:
                logger.warning(
                    "[view] Dependencies not found in the addons paths (%s): the anchors of the"
                    " inherited views and the models used are not checked (give --context-path)."
                    " File %s:1"
                    % (", ".join(unknown), module_migration._module_path / "__manifest__.py")
                )
            for path, line, message in views.check_module(
                module_migration._module_path, index, reference_modules
            ):
                logger.error("[view] %s. File %s:%s" % (message, path, line))

        # models inherited / used as comodel that do not exist in the target
        from .analysis import models

        model_index = models.ModelIndex.build(
            reference + list(options.context_path) + [self._directory_path]
        )
        for module_migration in self._module_migrations:
            for path, line, message in models.check_module(
                module_migration._module_path, model_index
            ):
                logger.error("%s. File %s:%s" % (message, path, line))
            # paths of @api.depends / related= through fields that do not exist
            for path, line, message in models.check_field_paths(
                module_migration._module_path, model_index
            ):
                logger.error("%s. File %s:%s" % (message, path, line))

        # names imported from the addons of the target Odoo
        from .analysis import imports

        import_index = imports.ImportIndex(reference)
        for module_migration in self._module_migrations:
            for path, line, message in imports.check_module(
                module_migration._module_path, import_index
            ):
                logger.error("%s. File %s:%s" % (message, path, line))

    def _run_upgrade_code(self):
        init_version = self._migration_steps[0]["init_version_name"]
        target_version = self._migration_steps[-1]["target_version_name"]
        if float(target_version) < 18:
            logger.info("upgrade_code: no official script before 18.0, skipped")
            return
        if float(target_version) >= 20:
            from .upgrade_code.prepare import move_access_records

            for module_migration in self._module_migrations:
                try:
                    move_access_records(module_migration._module_path)
                except Exception as e:  # noqa: BLE001
                    logger.error(
                        "Access records not prepared for upgrade_code (%s: %s). File %s"
                        % (type(e).__name__, e, module_migration._module_path / "__manifest__.py")
                    )
        self.upgrade_code_result = run_upgrade_code(
            self._upgrade_code_options,
            [m._module_path for m in self._module_migrations],
            init_version,
            target_version,
        )
