# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import ast
import importlib
import inspect
import os
import pathlib
import pkgutil
import re
import subprocess
import time
import traceback

from . import report, tools
from .base_migration_script import BaseMigrationScript
from .config import _ALLOWED_EXTENSIONS, _AVAILABLE_MIGRATION_STEPS, _MANIFEST_NAMES
from .exception import ConfigException
from .log import logger
from .module_migration import ModuleMigration
from .tools import _get_latest_version_code, _run
from .upgrade_code import run_upgrade_code


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
        remove_migration_folder=False,
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
        default_author="",
        ollama_review=False,
        ollama_apply=False,
        ollama_repair=False,
        ollama_max_attempts=3,
        ollama_max_minutes=20,
        ollama_max_diff_lines=200,
        ollama_url="http://127.0.0.1:11434",
        ollama_model="",
        ollama_timeout=600,
        ollama_max_context=10000,
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
        # Target indexes of the view/model/import checks (None without sources)
        self._target_indexes = None
        self._report = write_report
        self._set_installable = set_installable
        self._report_dir = pathlib.Path(report_dir).resolve() if report_dir else None
        self._format_code = format_code
        self._clean_imports = clean_imports
        self._manifest_layout = manifest_layout
        self._default_website = default_website
        self._default_author = default_author
        self._ollama_review = ollama_review or ollama_apply or ollama_repair
        self._ollama_apply = ollama_apply
        self._ollama_repair = ollama_repair
        self._ollama_max_attempts = ollama_max_attempts
        self._ollama_max_minutes = ollama_max_minutes
        self._ollama_max_diff_lines = ollama_max_diff_lines
        self._ollama_url = ollama_url
        self._ollama_model = ollama_model
        self._ollama_timeout = ollama_timeout
        self._ollama_max_context = ollama_max_context
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
            logger.warning(
                "Migration folders are always preserved because they may be required "
                "to upgrade production data; the removal option is ignored"
            )
        
        all_packages = importlib.import_module("odoo_module_migrate.migration_scripts")
        migration_start = float(self._migration_steps[0]["init_version_code"])
        migration_end = float(self._migration_steps[-1]["target_version_code"])

        for loader, name, is_pkg in pkgutil.walk_packages(all_packages.__path__):
            if name == "migrate_allways":
                continue

            full_name = f"{all_packages.__name__}.{name}"
            real_name = name.replace("allways", _get_latest_version_code()) if "allways" in name else name
            splitted_name = real_name.split("_")

            script_start = float(splitted_name[1])
            script_end = float(splitted_name[2])

            if not (script_start >= migration_end or script_end <= migration_start):
                self._migration_scripts.extend(self._load_migration_script(full_name))

        scripts = [inspect.getfile(x.__class__).split("/")[-1] for x in self._migration_scripts]
        logger.debug("Migration scripts to execute:\n- " + "\n- ".join(scripts))

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
            self._check_repository_merged_modules()
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
                              default_website=self._default_website,
                              default_author=self._default_author)
            if self._format_code or self._clean_imports:
                self._format_changed_files()
            if float(init_version) < 20 <= float(target_version):
                self._check_access_records_left()
            if self.report_collector:
                self._reconcile_text_rule_diagnostics()
            if self.report_collector and self._ollama_review:
                self._run_intelligent_review(init_version, target_version)
                # Exact model edits can make a regex diagnostic obsolete.
                if self._ollama_apply or self._ollama_repair:
                    if self._format_code or self._clean_imports:
                        self._format_changed_files()
                    self._reconcile_text_rule_diagnostics()
            # Ollama edits, when explicitly enabled, must pass through the
            # project's hooks too. This remains after every source mutation.
            self._run_pre_commit_if_configured()
            if self.report_collector:
                self._reconcile_text_rule_diagnostics()
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

    def _check_repository_merged_modules(self):
        """Report old module directories even when they were not selected.

        Dependency rewriting alone cannot reveal a sibling OCA module that was
        merged upstream. Keeping both directories would lose the database
        module/XML-ID transfer required during an upgrade.
        """
        selected = {item._module_name for item in self._module_migrations}
        current_rules = []
        current_old = set()
        for script in self._migration_scripts:
            script.parse_rules()
            for rule in script._DEPRECATED_MODULES:
                if len(rule) > 2 and rule[1] == "merged":
                    current_rules.append(rule)
                    current_old.add(rule[0])

        # Also inspect merges from earlier transitions. A stale OCA directory
        # can still be present when a user starts directly from 19.0 even if
        # that module was already merged while moving to 19.0.
        import yaml

        rules = list(current_rules)
        target_code = int(float(self._migration_steps[-1]["target_version_name"]) * 10)
        rules_root = pathlib.Path(__file__).parent / "migration_scripts/deprecated_modules"
        for step in rules_root.glob("migrate_*_*"):
            match = re.fullmatch(r"migrate_(\d+)_(\d+)", step.name)
            if not match or int(match.group(2)) > target_code:
                continue
            for source in sorted(step.glob("*.yaml")):
                for rule in yaml.safe_load(source.read_text(encoding="utf-8")) or []:
                    if len(rule) > 2 and rule[1] == "merged":
                        rules.append(rule)

        reported = set()
        for rule in rules:
            old, _state, target = rule[:3]
            if old in reported or (old in selected and old in current_old):
                continue
            path = self._directory_path / old
            if not path.is_dir() or not self._is_module_path(path):
                continue
            reported.add(old)
            previous_report = None
            if self.report_collector and target in self.report_collector.reports:
                previous_report = self.report_collector.current
                self.report_collector.current = self.report_collector.reports[target]
            logger.error(
                "[repository] Module '%s' is merged into '%s' in the target "
                "version but its directory is still present. Merge its code "
                "and add a pre-migration database module/XML-ID transfer. "
                "File %s:1",
                old,
                target,
                next(
                    (path / name for name in _MANIFEST_NAMES if (path / name).exists()),
                    path,
                ),
            )
            if self.report_collector and target in self.report_collector.reports:
                self.report_collector.current = previous_report

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

    def _intelligence_context(self, init_version, target_version, item):
        """Checker, target data and repair context shared by review and repair."""
        from .intelligence.applicators import TargetViewTrees
        from .intelligence.diagnostics import FullModuleDiagnosticsChecker

        indexes = self._target_indexes
        checker = FullModuleDiagnosticsChecker(
            target_version,
            self._migration_scripts,
            indexes=indexes,
            init_version=init_version,
            module_name=item._module_name,
        )
        context = {"known_modules": None, "dependency_graph": None, "target_view_tree": None}
        lookup = None
        if indexes is not None:
            graph = {}
            for index in (indexes.view_index, indexes.model_index):
                for name, depends in (getattr(index, "depends", None) or {}).items():
                    graph.setdefault(name, list(depends))
            if graph:
                context["known_modules"] = set(graph)
                context["dependency_graph"] = graph
            if indexes.view_index is not None:
                context["target_view_tree"] = TargetViewTrees(indexes.view_index)
            lookup = _target_symbol_lookup(indexes)
        options = self._upgrade_code_options
        upgrade_code_dir = None
        if options is not None and (pathlib.Path(options.odoo_root) / "odoo" / "upgrade_code").is_dir():
            upgrade_code_dir = pathlib.Path(options.odoo_root) / "odoo" / "upgrade_code"
        return {
            "checker": checker,
            "context": context,
            "symbol_lookup": lookup,
            "reference_paths": list(options.addons_path) if options else [],
            "context_paths": list(options.context_path) if options else [],
            "upgrade_code_dir": upgrade_code_dir,
        }

    def _run_intelligent_review(self, init_version, target_version):
        """Attach an optional local Ollama review; never abort the migration."""
        from . import intelligent_review
        from .intelligence.provider import OllamaProvider

        provider = None
        for item in self._module_migrations:
            module_report = self.report_collector.reports[item._module_name]
            self.report_collector.current = module_report
            started = time.monotonic()
            try:
                if provider is None:
                    # One provider for every module: model choice, hardware
                    # probing and the loaded model are reused.
                    provider = OllamaProvider(
                        self._ollama_url,
                        intelligent_review.configured_model(self._ollama_model),
                        self._ollama_timeout,
                    )
                shared = self._intelligence_context(init_version, target_version, item)
                checker = shared["checker"]
                if self._ollama_repair:
                    session = intelligent_review.repair_module(
                        item._module_path,
                        module_report,
                        init_version,
                        target_version,
                        provider=provider,
                        max_attempts=self._ollama_max_attempts,
                        max_minutes=self._ollama_max_minutes,
                        max_diff_lines=self._ollama_max_diff_lines,
                        diagnostics_checker=checker.check_module,
                        reference_paths=shared["reference_paths"],
                        context_paths=shared["context_paths"],
                        upgrade_code_dir=shared["upgrade_code_dir"],
                        timeout=self._ollama_timeout,
                        max_context=self._ollama_max_context,
                        coverage=checker.coverage(),
                        symbol_lookup=shared["symbol_lookup"],
                        **shared["context"],
                    )
                    review = _review_from_session(intelligent_review, session)
                    resolved = session.resolved
                else:
                    review = intelligent_review.review_module(
                        module_report,
                        init_version,
                        target_version,
                        provider=provider,
                        timeout=self._ollama_timeout,
                        max_context=self._ollama_max_context,
                        reference_paths=shared["reference_paths"],
                        context_paths=shared["context_paths"],
                        upgrade_code_dir=shared["upgrade_code_dir"],
                    )
                    review.mode = "application vérifiée" if self._ollama_apply else "revue"
                    review.coverage = checker.coverage()
                    intelligent_review.assess_safe_edits(
                        item._module_path,
                        review,
                        apply=self._ollama_apply,
                        checker=checker.check_module,
                        max_diff_lines=self._ollama_max_diff_lines,
                        symbol_lookup=shared["symbol_lookup"],
                    )
                    resolved = [
                        key for rec in review.recommendations if rec.status == "applied" for key in rec.resolved
                    ]
                for rec in review.recommendations:
                    if rec.status == "applied":
                        logger.info(
                            "Ollama edit applied after deterministic verification (%s, score %.2f). File %s:%s",
                            rec.operation_type, rec.objective_score or 0.0,
                            item._module_path / rec.file, rec.line or 1,
                        )
                _drop_resolved_entries(module_report, resolved)
                review.metrics["llm"] = [vars(call) for call in provider.stats.calls]
                provider.stats.calls = []
                review.metrics["seconds"] = round(time.monotonic() - started, 2)
                module_report.intelligent_review = review
                _write_metrics(item._module_name, review)
            except intelligent_review.OllamaError as exc:
                module_report.intelligent_review = intelligent_review.Review(
                    model=self._ollama_model,
                    error=str(exc),
                )
                # The optional reviewer being offline must not create a
                # migration TODO or change the module risk level.
                self.report_collector.current = None
                logger.warning("Local Ollama review unavailable: %s", exc)
            except Exception as exc:  # noqa: BLE001 - the optional layer never aborts a migration
                module_report.intelligent_review = intelligent_review.Review(
                    model=self._ollama_model,
                    error=f"échec interne de l'assistance locale, aucune modification publiée : {type(exc).__name__}: {exc}",
                )
                self.report_collector.current = None
                logger.warning("Local Ollama assistance failed: %s: %s", type(exc).__name__, exc)
                logger.debug(traceback.format_exc())
        self.report_collector.current = None

    def _reconcile_text_rule_diagnostics(self):
        """Re-evaluate regex TODOs against the final migrated sources.

        A later official script, Ruff or the quality pass may remove the text
        that originally triggered a rule. Rebuilding these entries here keeps
        the report aligned with the code the user will actually review.
        """
        from .analysis.module_diagnostics import text_rule_entries, text_rules

        rules = text_rules(self._migration_scripts)
        known_messages = {
            message
            for extension_rules in rules.values()
            for _pattern, message, _level in extension_rules
        }
        for item in self._module_migrations:
            module_report = self.report_collector.reports[item._module_name]
            module_report.entries[:] = [
                entry
                for entry in module_report.entries
                if entry.message not in known_messages
            ]
            for entry in text_rule_entries(item._module_path, rules):
                if entry not in module_report.entries:
                    module_report.entries.append(entry)

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
                    prefix = [ruff, "check", "--isolated", "--fix", "--select", "F401,I", "--no-unsafe-fixes"]
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
                    if operation == "check":
                        from .quality import clean_python_spacing

                        for path in batch:
                            text = tools._read_content(path)
                            cleaned = clean_python_spacing(text)
                            if cleaned != text:
                                tools._write_content(path, cleaned)

    def _check_access_records_left(self):
        """ir.rule / ir.model.access left in XML once converted (by Odoo's
        19.4-00-ir-access.py or by the fallback of migrate_190_200)."""
        from .analysis.module_diagnostics import access_left_diagnostics

        init_version = self._migration_steps[0]["init_version_name"]
        target_version = self._migration_steps[-1]["target_version_name"]
        for module_migration in self._module_migrations:
            for _level, message, path, line in access_left_diagnostics(
                module_migration._module_path, init_version, target_version
            ):
                logger.warning("%s. File %s:%s" % (message, path, line))

    def _check_view_anchors(self):
        """Inherited views anchored on fields absent from the target views."""
        from .analysis import views

        options = self._upgrade_code_options
        reference = list(options.addons_path)
        from .analysis.module_diagnostics import (
            TargetIndexes,
            compose_index,
            import_diagnostics,
            model_diagnostics,
            resolve_index_dependencies,
            view_diagnostics,
        )

        logger.info("Checking the view anchors against the target Odoo views...")
        # The migrated modules are added on top of a base index of every other
        # addon: the optional repair replays the checks on a copy composed the
        # same way, with the copy replacing its module.
        index_paths = reference + list(options.context_path) + [self._directory_path]
        run_modules = {m._module_name: m._module_path for m in self._module_migrations}
        module_rules = self._index_dependency_rules()
        view_base = views.ViewIndex.build(index_paths, exclude=run_modules)
        resolve_index_dependencies(view_base, module_rules)
        index = compose_index(view_base, run_modules, module_rules)
        reference_modules = {m.name for m in views._module_dirs(reference)}
        menu_parent_hints = []
        for script in self._migration_scripts:
            script.parse_rules()
            menu_parent_hints.extend(script._MENU_PARENT_HINTS)

        self._target_indexes = TargetIndexes(
            float(self._migration_steps[-1]["target_version_name"]),
            view_base=view_base,
            run_modules=run_modules,
            module_rules=module_rules,
            view_index=index,
            reference_modules=frozenset(reference_modules),
            menu_parent_hints=menu_parent_hints,
            removed_fields=[
                rule
                for script in self._migration_scripts
                for rule in script._REMOVED_FIELDS
            ],
        )
        for module_migration in self._module_migrations:
            widget_dependencies = views.apply_known_widget_dependencies(
                module_migration._module_path, index
            )
            for dependency in widget_dependencies:
                logger.info(
                    "Added uniquely resolved widget dependency %s. File %s:1",
                    dependency,
                    module_migration._module_path / "__manifest__.py",
                )
            for level, message, path, line in view_diagnostics(
                module_migration._module_path, self._target_indexes,
                module_migration._module_name,
            ):
                getattr(logger, level)("%s. File %s:%s", message, path, line)

        # models inherited / used as comodel that do not exist in the target
        from .analysis import models

        logger.info("Indexing target models and Python dependencies (cached source summaries)...")
        model_base = models.ModelIndex.build(index_paths, exclude=run_modules)
        resolve_index_dependencies(model_base, module_rules)
        for script in self._migration_scripts:
            for rule in script._RENAMED_METHODS:
                if len(rule) >= 3:
                    model_base.renamed_methods.setdefault(
                        (rule[0], rule[1]), (rule[2], rule[3] if len(rule) > 3 else "")
                    )
        model_index = compose_index(model_base, run_modules, module_rules)
        self._target_indexes.model_base = model_base
        self._target_indexes.model_index = model_index
        from .analysis import python_checks
        for module_migration in self._module_migrations:
            additions = python_checks.apply_unambiguous_dependencies(
                module_migration._module_path, model_index
            )
            for dependency in additions:
                logger.info(
                    "Added uniquely resolved Python dependency %s. File %s:1",
                    dependency,
                    module_migration._module_path / "__manifest__.py",
                )
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
            signature_changes = python_checks.apply_override_signature_migrations(
                module_migration._module_path, model_index
            )
            for changed_path, changed_line, detail in signature_changes:
                logger.info(
                    "Synchronized override signature (%s). File %s:%s",
                    detail,
                    changed_path,
                    changed_line,
                )
            if float(self._migration_steps[-1]["target_version_name"]) >= 20:
                base_common_changes = python_checks.apply_base_common_compatibility(
                    module_migration._module_path
                )
                for changed_path, changed_line, class_name in base_common_changes:
                    logger.info(
                        "Set %s._test_user_groups = None for Odoo 20 BaseCommon compatibility. File %s:%s",
                        class_name,
                        changed_path,
                        changed_line,
                    )
                binary_changes = python_checks.apply_binaryvalue_migrations(
                    module_migration._module_path, model_index
                )
                for changed_path, changed_line, detail in binary_changes:
                    logger.info(
                        "Migrated Odoo 20 BinaryValue operation (%s). File %s:%s",
                        detail,
                        changed_path,
                        changed_line,
                    )
            runtime_changes = python_checks.apply_runtime_api_migrations(
                module_migration._module_path,
                model_index,
                float(self._migration_steps[-1]["target_version_name"]),
            )
            for changed_path, changed_line, detail in runtime_changes:
                logger.info(
                    "Migrated runtime API (%s). File %s:%s",
                    detail,
                    changed_path,
                    changed_line,
                )
            logger.info("Checking Python and field callbacks: %s", module_migration._module_name)
            for level, message, path, line in model_diagnostics(
                module_migration._module_path, self._target_indexes,
                module_migration._module_name,
            ):
                getattr(logger, level)("%s. File %s:%s", message, path, line)

        # names imported from the addons of the target Odoo
        from .analysis import imports

        self._target_indexes.import_index = imports.ImportIndex(reference)
        for module_migration in self._module_migrations:
            for level, message, path, line in import_diagnostics(
                module_migration._module_path, self._target_indexes
            ):
                getattr(logger, level)("%s. File %s:%s", message, path, line)

    def _resolve_index_dependencies(self, index):
        from .analysis.module_diagnostics import resolve_index_dependencies

        resolve_index_dependencies(index, self._index_dependency_rules())

    def _index_dependency_rules(self):
        rules = []
        for script in self._migration_scripts:
            script.parse_rules()
            rules.extend(r for r in script._DEPRECATED_MODULES if len(r) > 2 and r[1] in ("merged", "renamed"))
        return rules

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


def _target_symbol_lookup(indexes):
    """Whether a symbol is known to the target indexes (model, field, method, XML id, module)."""
    model_index, view_index = indexes.model_index, indexes.view_index
    cache = {}

    def lookup(symbol):
        if model_index is not None:
            if not cache:
                cache["fields"] = set().union(*model_index.fields.values()) if model_index.fields else set()
                cache["methods"] = set().union(*model_index.methods.values()) if model_index.methods else set()
            if symbol in model_index.defined or symbol in cache["fields"] or symbol in cache["methods"]:
                return True
        return view_index is not None and (symbol in view_index.xmlids or symbol in view_index.depends)

    return lookup


def _review_from_session(intelligent_review, session):
    """Human-readable review of a repair session: every attempt, not only successes."""
    applied = len(session.applied_operations)
    review = intelligent_review.Review(
        model=session.model,
        summary=(
            f"Réparation bornée : {len(session.attempts)} tentative(s), {applied} opération(s) "
            f"publiée(s), diagnostics rejouables {session.initial_todos} -> {session.final_todos}."
        ),
        error=session.error,
        elapsed_seconds=session.total_time_seconds,
        repair_session=session,
        mode="réparation autonome",
        coverage=session.coverage,
        metrics=dict(session.metrics),
    )
    for record in session.attempts:
        op = record.operation or {}
        confidence = record.confidence
        if record.status in {"applied", "advice"}:
            status = record.status
        elif record.status == "rejected":
            status = f"rejected: {record.reason}"
        else:
            status = f"{record.status}: {record.reason}"
        evidence = op.get("evidence", "")
        review.recommendations.append(intelligent_review.Recommendation(
            title=f"Tentative {record.attempt_number} : {op.get('type', 'aucune opération')}",
            diagnosis=str(op.get("description", "")) or (record.reason if record.status == "advice" else ""),
            action=f"{op.get('type')} sur {op.get('file')}" if op else "",
            confidence="",
            file=str(op.get("file", "")),
            line=op.get("line") if isinstance(op.get("line"), int) else 0,
            evidence=" ".join(map(str, evidence)) if isinstance(evidence, list) else str(evidence),
            operation_type=str(op.get("type", "")),
            status=status,
            objective_score=confidence.score if confidence else None,
            objective_confidence=confidence.level if confidence else "non évaluée",
            validation_level=confidence.validation_level if confidence else "non validée",
            diff=record.diff,
            reason=record.reason,
            factors=confidence.factors if confidence else [],
            evidence_chunks=record.evidence,
            resolved=record.resolved,
            validations=record.validations,
        ))
    return review


def _drop_resolved_entries(module_report, resolved):
    """Remove from the report the TODOs a verified edit resolved (by key, once each)."""
    from .intelligence.diagnostics import diagnostic_key

    remaining = list(resolved)
    kept = []
    for entry in module_report.entries:
        key = diagnostic_key(entry)
        if key in remaining:
            remaining.remove(key)
            continue
        kept.append(entry)
    module_report.entries[:] = kept


def _write_metrics(module_name, review):
    """Optional JSON-lines metrics (ODOO_MIGRATOR_METRICS=<file>), outside the report."""
    import json

    target = os.environ.get("ODOO_MIGRATOR_METRICS")
    if not target:
        return
    record = {"module": module_name, "mode": review.mode, "model": review.model, **review.metrics}
    with open(target, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
