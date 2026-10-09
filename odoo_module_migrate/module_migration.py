# Copyright (C) 2019 - Today: GRAP (http://www.grap.coop)
# @author: Sylvain LE GAL (https://twitter.com/legalsylvain)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from .log import logger

from .config import _MANIFEST_NAMES
from .tools import (
    _run, _rename_path, changed_files, hash_tree, restore_formats, snapshot_formats,
)


class ModuleMigration:

    _migration = False
    _module_name = False
    _module_path = False

    def __init__(self, migration, module_name):
        self._migration = migration
        self._module_name = module_name
        self._module_path = self._migration._directory_path / module_name

    def run(self):
        self.apply_scripts()
        self.finalize()

    def apply_scripts(self):
        collector = self._migration.report_collector
        if collector:  # before the first log record of the module
            collector.current = collector.reports.get(self._module_name)
        logger.info(
            "[%s] Running migration from %s to %s"
            % (
                self._module_name,
                self._migration._migration_steps[0]["init_version_name"],
                self._migration._migration_steps[-1]["target_version_name"],
            )
        )

        self._formats = snapshot_formats(self._module_path)
        self._hashes_before = hash_tree(self._module_path)
        self._protected_oca_icons = {}
        if self._migration._is_oca_module(self._module_path):
            description = self._module_path / "static" / "description"
            if description.is_dir():
                self._protected_oca_icons = {
                    path: path.read_bytes()
                    for path in description.glob("icon.*")
                    if path.is_file()
                }
        import ast
        from .tools import _read_content
        try:
            self._original_data = ast.literal_eval(_read_content(self._get_manifest_path())).get("data", [])
        except (ValueError, SyntaxError):
            self._original_data = []

        # Apply migration script
        for migration_script in self._migration._migration_scripts:
            migration_script.run(
                self._module_path,
                self._get_manifest_path(),
                self._module_name,
                self._migration._migration_steps,
                self._migration._directory_path,
                self._migration._commit_enabled,
            )

    def finalize(self):
        self.restore()
        self.commit()

    def restore(self):
        for path, content in getattr(self, "_protected_oca_icons", {}).items():
            if not path.exists() or path.read_bytes() != content:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                logger.info("Restored original OCA module icon. File %s", path)
        restore_formats(self._formats)

    def changed_files(self, ignore=()):
        return changed_files(self._hashes_before, hash_tree(self._module_path), ignore)

    def commit(self):
        # Run pre-commit before final commit to format any changes made
        # during migration scripts execution
        self._commit_changes(
            "[MIG] %s: Migration to %s"
            % (
                self._module_name,
                self._migration._migration_steps[-1]["target_version_name"],
            )
        )

    def _get_manifest_path(self):
        for manifest_name in _MANIFEST_NAMES:
            manifest_path = self._module_path / manifest_name
            if manifest_path.exists():
                return manifest_path

    def _rename_file(self, module_path, old_file_path, new_file_path):
        _rename_path(
            module_path, old_file_path, new_file_path, self._migration._commit_enabled
        )

    def _commit_changes(self, commit_name):
        if not self._migration._commit_enabled:
            return
        directory = self._migration._directory_path
        if not _run(["git", "status", "--porcelain", "--", self._module_name], path=directory):
            return
        logger.info(
            "Commit changes for %s. commit name '%s'" % (self._module_name, commit_name)
        )
        _run(["git", "add", "--all", "--", self._module_name], path=directory)
        _run(["git", "commit", "--no-verify", "-m", commit_name, "--", self._module_name], path=directory)
