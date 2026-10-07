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
        format_code=False,
        format_config_root=None,
        use_bundled_upgrade=False,
        context_paths=(),
        reference_paths=(),
        clean_imports=False,
        manifest_layout=False,
        default_website="",
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
        self._format_code = format_code
        self._clean_imports = clean_imports
        self._manifest_layout = manifest_layout
        self._default_website = default_website
        self._format_config_root = pathlib.Path(format_config_root).resolve() if format_config_root else None
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
        if use_bundled_upgrade and not self._upgrade_code_options and float(target_version_name) >= 18:
            from .upgrade_code.bundled import options
            self._upgrade_code_options = options(target_version_name, [*context_paths, self._directory_path], reference_paths)

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
            files = [str(p.relative_to(self._directory_path))
                     for m in self._module_migrations for p in m._module_path.rglob("*")
                     if p.is_file() and not {".git", "__pycache__"}.intersection(p.parts)]
            if files:
                _run(["pre-commit", "run", "--files", *files], path=self._directory_path, check=False)
        except FileNotFoundError:
            logger.warning("pre-commit is not installed: skipping it")

    def _run_pre_commit(self, module_names):
        logger.info("Run pre-commit")
        self._run_pre_commit_if_configured()
        if self._commit_enabled:
            logger.info("Stage and commit changes done by pre-commit")
            _run(["git", "add", "-A", "--", *module_names], path=self._directory_path)
            # Don't fail if there is nothing to commit
            _run(
                [
                    "git", "commit", "--no-verify", "-m",
                    "[IMP] %s: pre-commit execution" % ", ".join(module_names), "--", *module_names,
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
                        for item in self._module_migrations:
                            logger.error("[incomplete] %s failed: %s: %s. File %s:1",
                                         step.__name__, type(e).__name__, e,
                                         item._module_path / "__manifest__.py")
                        logger.debug(traceback.format_exc())
            from .quality import finish_module
            for item in self._module_migrations:
                finish_module(item._module_path, cosmetic=not self._is_oca_module(item._module_path),
                              original_data=item._original_data, manifest_layout=self._manifest_layout,
                              default_website=self._default_website)
            if self._format_code or self._clean_imports:
                self._format_changed_files()
            if float(init_version) < 20 <= float(target_version):
                self._check_access_records_left()
            self._run_pre_commit_if_configured()
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

    def _format_changed_files(self):
        import shutil
        import sys

        ruff = shutil.which("ruff")
        if not ruff:
            candidate = pathlib.Path(sys.executable).parent / ("ruff.exe" if os.name == "nt" else "ruff")
            ruff = str(candidate) if candidate.exists() else None
        if not ruff:
            raise ConfigException("--format requires ruff: install it with python -m pip install ruff")
        config_args = []
        root = self._format_config_root or self._directory_path
        for directory in [root, *root.parents]:
            config = next((directory / name for name in (".ruff.toml", "ruff.toml", "pyproject.toml")
                           if (directory / name).is_file() and
                           (name != "pyproject.toml" or "[tool.ruff" in (directory / name).read_text(encoding="utf-8"))), None)
            if config:
                config_args = ["--config", str(config)]
                break
        for item in self._module_migrations:
            if self._is_oca_module(item._module_path):
                continue
            for operation in ("check", "format"):
                if operation == "check":
                    if not self._clean_imports:
                        continue
                    paths = [p for p in tools.get_files(item._module_path, (".py",)) if p.name != "__init__.py"]
                    prefix = [ruff, "check", "--isolated", "--fix", "--select", "F401", "--no-unsafe-fixes"]
                else:
                    if not self._format_code:
                        continue
                    paths = [item._module_path / change.removesuffix(" (ajouté)") for change in item.changed_files()]
                    paths = [p for p in paths if p.is_file() and p.suffix == ".py"]
                    prefix = [ruff, "format", *config_args]
                for offset in range(0, len(paths), 32):
                    batch = paths[offset:offset + 32]
                    command = prefix + [str(p) for p in batch]
                    result = subprocess.run(command, cwd=self._directory_path, capture_output=True, text=True)
                    if result.returncode:
                        logger.warning("Ruff: %s. File %s:1", (result.stderr or result.stdout).strip(), batch[0])

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
        self._resolve_index_dependencies(index)
        menu_parent_hints = []
        for script in self._migration_scripts:
            script.parse_rules()
            menu_parent_hints.extend(script._MENU_PARENT_HINTS)
        for module_migration in self._module_migrations:
            unknown = index.unknown_dependencies(module_migration._module_name)
            if unknown:
                logger.warning(
                    "[incomplete] Dependencies not found in the addons paths (%s): checks continue"
                    " against available sources; risk unknown (give --context-path)."
                    " File %s:1"
                    % (", ".join(unknown), module_migration._module_path / "__manifest__.py")
                )
            for path, line, message in views.check_module(
                module_migration._module_path, index, reference_modules,
                menu_parent_hints,
            ):
                (logger.warning if unknown or "[incomplete]" in message else logger.error)("[view] %s. File %s:%s" % (message, path, line))
            for path, line, message in views.check_duplicate_fields(module_migration._module_path, index):
                logger.warning("[view] %s. File %s:%s", message, path, line)

        # models inherited / used as comodel that do not exist in the target
        from .analysis import models

        logger.info("Indexing target models and Python dependencies (cached source summaries)...")
        model_index = models.ModelIndex.build(
            reference + list(options.context_path) + [self._directory_path]
        )
        self._resolve_index_dependencies(model_index)
        for script in self._migration_scripts:
            for rule in script._RENAMED_METHODS:
                if len(rule) >= 3:
                    model_index.renamed_methods.setdefault(
                        (rule[0], rule[1]), (rule[2], rule[3] if len(rule) > 3 else "")
                    )
        from .analysis import python_checks
        for module_migration in self._module_migrations:
            # The model index resolves relational aliases that the standalone
            # migration scripts cannot know (order.order_line -> line). Apply
            # each step in order so chained renames remain chained.
            for script in self._migration_scripts:
                renames = {}
                for rule in script._RENAMED_FIELDS:
                    if len(rule) > 2 and rule[2]:
                        renames.setdefault((rule[0], rule[1]), rule[2])
                changes = python_checks.apply_field_renames(
                    module_migration._module_path, model_index, renames
                )
                for changed_path, changed_line, model, old, new in changes:
                    logger.info(
                        "Renamed resolved field %s.%s -> %s. File %s:%s",
                        model, old, new, changed_path, changed_line,
                    )
            logger.info("Checking Python and field callbacks: %s", module_migration._module_name)
            log_model = logger.warning if model_index.unknown_dependencies(module_migration._module_name) else logger.error
            for path, line, level, message in python_checks.check_module(
                module_migration._module_path, model_index,
                float(self._migration_steps[-1]["target_version_name"]),
                precision_names=index.precisions,
            ):
                getattr(logger, level)("%s. File %s:%s", message, path, line)
            for path, line, message in models.check_module(
                module_migration._module_path, model_index
            ):
                log_model("%s. File %s:%s" % (message, path, line))
            # paths of @api.depends / related= through fields that do not exist
            for path, line, message in models.check_field_paths(
                module_migration._module_path, model_index
            ):
                log_model("%s. File %s:%s" % (message, path, line))

        # names imported from the addons of the target Odoo
        from .analysis import imports

        import_index = imports.ImportIndex(reference)
        for module_migration in self._module_migrations:
            for path, line, message in imports.check_module(
                module_migration._module_path, import_index
            ):
                logger.error("%s. File %s:%s" % (message, path, line))

    def _resolve_index_dependencies(self, index):
        rules = []
        for script in self._migration_scripts:
            script.parse_rules()
            rules.extend(r for r in script._DEPRECATED_MODULES if len(r) > 2 and r[1] in ("merged", "renamed"))
        from .manifest import apply_module_rules
        for name, dependencies in index.depends.items():
            index.depends[name] = apply_module_rules(dependencies, rules)[0]

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
        # Global script failures otherwise have no module path and disappear
        # from the per-module reports after the rule phase.
        for script in self.upgrade_code_result.scripts:
            failures = ([script["error"].strip().splitlines()[-1]] if script["error"] else [])
            failures += [r["message"] for r in script["logs"] if r["level"] in {"ERROR", "CRITICAL"}]
            for failure in failures:
                for item in self._module_migrations:
                    logger.error("[incomplete] upgrade_code %s: %s. File %s:1",
                                 script["name"], failure, item._module_path / "__manifest__.py")
