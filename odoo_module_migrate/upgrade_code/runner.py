# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Run Odoo's official ``odoo/upgrade_code`` scripts on selected modules only.

This file is executed as a standalone script by the *target* Odoo Python
(Odoo 20 needs Python >= 3.12): it must not import odoo_module_migrate.

Differences with ``odoo-bin upgrade_code``:

* every module of the addons path is *readable* (19.4-00-ir-access needs the
  ``res.groups`` definitions of odoo, enterprise and custom addons), but only
  files of the target modules are *written*. ``upgrade_code`` itself ignores
  ``--glob`` for files reached through ``file_manager.get_file()``, so it would
  rewrite every module of the addons path;
* files are read and written in UTF-8 with their BOM and line endings kept
  (``Path.read_text()`` uses cp1252 and CRLF on Windows);
* the scripts run one by one: a failing script is reported, the others run;
* ``owl3-migration.py`` (no version prefix, never selected by ``--from``) is
  run when the target version is >= 20.0;
* ``17.5-00-example.py`` is skipped ("broken, only serves as an example");
* the result is a JSON report (files, blocked writes, script logs).
"""

import argparse
import codecs
import contextlib
import io
import json
import logging
import sys
import traceback
from pathlib import Path

SKIPPED_SCRIPTS = {
    # "Don't use this script in production, it is broken" (its own docstring)
    "17.5-00-example.py",
    # Internal to Odoo: rewrites the charts of accounts of Odoo's l10n_* modules
    "19.3-00-account-groups.py",
    # The migrator's AST-based equivalent preserves comments and strings.
    "18.5-00-deprecated-properties.py",
}
OWL3_SCRIPT = "owl3-migration.py"


def _decode(raw):
    bom = raw.startswith(codecs.BOM_UTF8)
    if bom:
        raw = raw[len(codecs.BOM_UTF8):]
    try:
        text, encoding = raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        text, encoding = raw.decode("cp1252", errors="replace"), "cp1252"
    crlf = text.count("\r\n")
    newline = "\r\n" if crlf > text.count("\n") - crlf else "\n"
    return text.replace("\r\n", "\n"), (encoding, bom, newline)


def patch_file_accessor(uc):
    """Make FileAccessor keep the encoding, BOM and line endings of files."""

    def get_content(self):
        if not hasattr(self, "_format"):
            try:
                self._content, self._format = _decode(self.path.read_bytes())
            except FileNotFoundError:
                self._content, self._format = None, ("utf-8", False, "\n")
        return self._content

    def set_content(self, value):
        if get_content(self) != value:
            self._content = value
            self.dirty = True

    def save(self):
        if not self.dirty:
            return
        if self._content is None:
            self.path.unlink(missing_ok=True)
            return
        encoding, bom, newline = getattr(self, "_format", ("utf-8", False, "\n"))
        text = self._content.replace("\r\n", "\n")
        if newline != "\n":
            text = text.replace("\n", newline)
        data = text.encode(encoding, errors="replace")
        if bom:
            data = codecs.BOM_UTF8 + data
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".~{self.path.name}.tmp")
        tmp.write_bytes(data)
        tmp.replace(self.path)

    uc.FileAccessor.content = property(get_content, set_content)
    uc.FileAccessor._save = save


class _StubManifest:
    """Manifest of a module missing from the addons path (removed, renamed)."""

    def __init__(self, path):
        self.path = path
        self.addon = path.parent
        self.dirty = False
        self.content = "{'depends': [], 'data': []}"

    def _save(self):
        pass


def _manifest_depends(path):
    import ast

    try:
        return ast.literal_eval(_decode(path.read_bytes())[0]).get("depends", [])
    except Exception:  # noqa: BLE001
        return []


def patch_file_manager(uc, missing):
    """Deleted files are not listed anymore; unknown manifests are stubbed."""
    original_get_file = uc.FileManager.get_file

    def iter_files(self):
        return iter([
            f for f in self._files.values()
            if not (f.dirty and getattr(f, "_content", "") is None)
            and (not hasattr(self, "_target_roots") or any(
                f.path.is_relative_to(t) for t in self._target_roots))
        ])

    def get_file(self, module, file_name=None):
        if file_name is None:  # Odoo 18/19 use an absolute path argument.
            return original_get_file(self, module)
        if module not in self._modules and file_name == "__manifest__.py":
            aliases = getattr(self, "_module_aliases", {})
            if module in aliases:
                stub = _StubManifest(Path(module) / file_name)
                stub.content = repr({'depends': [aliases[module]], 'data': []})
                return stub
            missing.add(module)
            return _StubManifest(Path(module) / file_name)
        return original_get_file(self, module, file_name)

    uc.FileManager.__iter__ = iter_files
    uc.FileManager.get_file = get_file


def build_file_manager(uc, addons_path, context_path, targets, aliases=None):
    """A FileManager that sees the reference modules (odoo, enterprise...),
    the targets and their custom dependencies, but only lists target files."""
    file_manager = uc.FileManager(
        list(dict.fromkeys(addons_path + context_path)), glob="__odoo_module_migrate_none__"
    )
    file_manager._target_roots = tuple(targets)
    file_manager._module_aliases = aliases or {}
    def modules(manager, paths):
        if hasattr(manager, "_modules"):
            return manager._modules
        return {p.name: p for root in paths for p in Path(root).iterdir()
                if p.is_dir() and (p / "__manifest__.py").is_file()}
    file_manager._modules = modules(file_manager, list(dict.fromkeys(addons_path + context_path)))
    reference = modules(uc.FileManager(addons_path, glob="__odoo_module_migrate_none__"), addons_path)
    custom = {
        name: path for name, path in file_manager._modules.items()
        if name not in reference
    }
    # targets win over a module of the same name elsewhere
    for target in targets:
        custom[target.name] = target
    visible, todo = {}, [t.name for t in targets]
    while todo:
        name = todo.pop()
        if name in visible or name not in custom:
            continue
        visible[name] = custom[name]
        todo.extend(_manifest_depends(custom[name] / "__manifest__.py"))
    all_modules = {**reference, **visible}
    # Only installed dependencies can contribute security groups. Loading all
    # reference modules here needlessly parses every Odoo application's XML.
    needed, todo = set(), [t.name for t in targets] + ["base"]
    while todo:
        name = todo.pop()
        seen_aliases = set()
        while name in file_manager._module_aliases and name not in seen_aliases:
            seen_aliases.add(name)
            name = file_manager._module_aliases[name]
        if name in needed or name not in all_modules:
            continue
        needed.add(name)
        todo.extend(_manifest_depends(Path(all_modules[name]) / "__manifest__.py"))
    file_manager._modules = {name: path for name, path in all_modules.items() if name in needed}
    for target in targets:
        addon = file_manager._modules.get(target.name)
        if addon is None or Path(addon).resolve() != target.resolve():
            raise SystemExit(f"Module {target} is not in the addons path")
        for path in addon.rglob("*"):
            if (
                path.is_file()
                and path.suffix in uc.AVAILABLE_EXT
                and "__pycache__" not in path.parts
            ):
                file_manager._files[str(path)] = uc.FileAccessor(path, addon.parent)
    return file_manager


class _Collector(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.records = []

    def emit(self, record):
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            message = str(record.msg)
        self.records.append({"level": record.levelname, "message": message})


def select_scripts(uc, from_version, to_version, with_owl3):
    scripts = [
        (name, module)
        for name, module in uc.get_upgrade_code_scripts(
            uc.parse_version(from_version), uc.parse_version(to_version)
        )
        if name not in SKIPPED_SCRIPTS
    ]
    owl3 = uc.UPGRADE / OWL3_SCRIPT
    if with_owl3 and owl3.exists():
        from importlib.machinery import SourceFileLoader

        module = SourceFileLoader(OWL3_SCRIPT, str(owl3)).load_module()
        scripts.append((OWL3_SCRIPT, module))
    return scripts


def _dependency_closure(file_manager, targets):
    """Names of the targets and of all their dependencies (visible modules)."""
    result, todo = set(), [t.name for t in targets] + ["base"]
    while todo:
        name = todo.pop()
        if name in result or name not in file_manager._modules:
            continue
        result.add(name)
        todo.extend(_manifest_depends(Path(file_manager._modules[name]) / "__manifest__.py"))
    return result


def patch_ir_access(scripts, targets):
    """19.4-00-ir-access.py maps model XML ids to model names by reading the
    Python files of the file manager, i.e. only the target modules here: the
    models of the dependencies (e.g. account.model_account_payment) would stay
    unresolved and give an invalid ir.access.csv. The mapping is completed with
    the models of the dependencies, read only."""
    import functools
    from types import SimpleNamespace

    for _name, module in scripts:
        upgrade = getattr(module, "upgrade", None)
        original = getattr(upgrade, "get_model_xids", None)
        if original is None or not hasattr(module, "extract_model_names"):
            continue
        original = getattr(original, "__wrapped__", original)

        def get_model_xids(self, _original=original, _module=module):
            result = dict(_original(self))
            for addon_name in _dependency_closure(self.file_manager, targets):
                addon = Path(self.file_manager._modules[addon_name])
                for path in addon.rglob("*.py"):
                    if "tests" in path.parts or str(path) in self.file_manager._files:
                        continue
                    try:
                        content = _decode(path.read_bytes())[0]
                    except OSError:
                        continue
                    for model_name in _module.extract_model_names(SimpleNamespace(content=content)):
                        result.setdefault(_module.model_xmlid(addon_name, model_name), model_name)
            return result

        upgrade.get_model_xids = functools.cache(get_model_xids)

        def add_to_manifest(self, module_name, file_name):
            # The upstream line-based regex misses valid one-line manifests.
            # Locate the data list with AST and insert without changing comments.
            import ast
            file = self.file_manager.get_file(module_name, "__manifest__.py")
            content = file.content
            tree = ast.parse(content)
            mapping = tree.body[0].value
            node = next(v for k, v in zip(mapping.keys, mapping.values)
                        if isinstance(k, ast.Constant) and k.value == "data")
            if not isinstance(node, ast.List):
                raise ValueError("Manifest data must be a literal list")
            manifest = self.get_manifest(module_name)
            if file_name in manifest['data']:
                return
            lines = content.splitlines(keepends=True)
            def offset(line, col):
                return sum(map(len, lines[:line - 1])) + len(lines[line - 1].encode('utf-8')[:col].decode('utf-8'))
            start = offset(node.lineno, node.col_offset) + 1
            # Prepending needs no knowledge of a last item's trailing comma.
            file.content = content[:start] + repr(file_name) + ", " + content[start:]
            manifest['data'].insert(0, file_name)

        upgrade.add_to_manifest = add_to_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--odoo-root", required=True)
    parser.add_argument("--addons-path", required=True,
                        help="reference addons (odoo, enterprise...), comma separated")
    parser.add_argument("--context-path", default="",
                        help="custom addons: only dependencies of the targets are read")
    parser.add_argument("--modules", required=True, help="comma separated paths")
    parser.add_argument("--from", dest="from_version", required=True)
    parser.add_argument("--to", dest="to_version", required=True)
    parser.add_argument("--script", action="append", default=[],
                        help="run only these scripts (repeatable)")
    parser.add_argument("--owl3", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--module-aliases", default="{}")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(args.odoo_root).resolve()))
    from odoo.cli import upgrade_code as uc

    patch_file_accessor(uc)
    missing = set()
    patch_file_manager(uc, missing)
    targets = [Path(p).resolve() for p in args.modules.split(",") if p]
    addons_path = [str(Path(p).resolve()) for p in args.addons_path.split(",") if p]
    context_path = [str(Path(p).resolve()) for p in args.context_path.split(",") if p]
    for parent in {str(t.parent) for t in targets}:
        if parent not in context_path:
            context_path.append(parent)

    file_manager = build_file_manager(uc, addons_path, context_path, targets, json.loads(args.module_aliases))
    scripts = select_scripts(uc, args.from_version, args.to_version, args.owl3)
    if args.script:
        scripts = [s for s in scripts if s[0] in args.script]
    patch_ir_access(scripts, targets)

    collector = _Collector()
    root_logger = logging.getLogger()
    root_logger.addHandler(collector)
    root_logger.setLevel(logging.INFO)

    report = {"scripts": [], "updated": [], "deleted": [], "blocked": [], "summary": []}
    for name, module in scripts:
        collector.records = []
        stdout = io.StringIO()
        error = None
        try:
            with contextlib.redirect_stdout(stdout):
                module.upgrade(file_manager)
        except Exception:  # noqa: BLE001 - reported, the other scripts still run
            error = traceback.format_exc()
        report["scripts"].append({
            "name": name,
            "error": error,
            "logs": collector.records,
            "stdout": stdout.getvalue(),
        })

    for file in sorted(file_manager._files.values(), key=lambda f: str(f.path)):
        if not file.dirty:
            continue
        path = file.path.resolve()
        if not any(path.is_relative_to(t) for t in targets):
            report["blocked"].append(str(path))
            continue
        report["deleted" if file.content is None else "updated"].append(str(path))
        if not args.dry_run:
            file._save()
    report["summary"] = list(getattr(file_manager, "_summary", []))
    report["missing_modules"] = sorted(missing)

    Path(args.output).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
