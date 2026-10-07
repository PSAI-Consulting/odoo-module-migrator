# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""--dry-run: migrate a temporary copy and print the diff."""

import difflib
import pathlib
import shutil
import sys
import tempfile

from .config import _MANIFEST_NAMES
from .log import logger
from .migration import Migration

_IGNORED_PARTS = {"__pycache__", ".git"}


def _is_module(path):
    return any((path / name).exists() for name in _MANIFEST_NAMES)


def _files(root):
    return {
        p.relative_to(root).as_posix(): p
        for p in root.rglob("*")
        if p.is_file() and not _IGNORED_PARTS.intersection(p.parts)
    }


def _read_lines(path):
    try:
        return path.read_bytes().decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return None


def module_diff(before_root, after_root, label):
    """Unified diff between two versions of a module directory."""
    before, after = _files(before_root), _files(after_root)
    chunks = []
    for rel in sorted(set(before) | set(after)):
        old = before.get(rel)
        new = after.get(rel)
        if old and new and old.read_bytes() == new.read_bytes():
            continue
        old_lines = _read_lines(old) if old else []
        new_lines = _read_lines(new) if new else []
        if old_lines is None or new_lines is None:
            chunks.append(f"Binary file {label}/{rel} differs\n")
            continue
        chunks.extend(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{label}/{rel}" if old else "/dev/null",
                tofile=f"b/{label}/{rel}" if new else "/dev/null",
            )
        )
    return "".join(chunks)


def run_dry(args, module_names, upgrade_code_options=None, out=None):
    out = out or sys.stdout
    source = pathlib.Path(args.directory).resolve()
    if not module_names:
        module_names = [p.name for p in source.iterdir() if p.is_dir() and _is_module(p)]
    with tempfile.TemporaryDirectory(prefix="odoo-migrate-dry-") as tmp:
        work = pathlib.Path(tmp)
        for name in module_names:
            if (source / name).is_dir():
                shutil.copytree(source / name, work / name)
        logger.info("Dry run: migrating a copy in %s", work)
        migration = Migration(
            str(work),
            args.init_version_name,
            args.target_version_name,
            list(module_names),
            False,  # format_patch
            args.remote_name,
            False,  # commit_enabled
            False,  # pre_commit
            args.remove_migration_folder,
            args.no_oca_modules,
            upgrade_code_options=upgrade_code_options,
            write_report=bool(args.report_dir),
            report_dir=args.report_dir,
            set_installable=getattr(args, "set_installable", False),
            format_code=getattr(args, "format_code", False),
            format_config_root=source,
            clean_imports=not getattr(args, "keep_unused_imports", True),
            manifest_layout=not getattr(args, "no_manifest_format", True),
            default_website=getattr(args, "default_website", ""),
        )
        migration.run()
        for name in module_names:
            if (source / name).is_dir():
                out.write(module_diff(source / name, work / name, name))
