# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Read-only diagnostics of one module, shared by the migration and the replay.

The migration logs these findings into the module report. The optional repair
loop replays them on a temporary copy after each candidate edit. Both must use
the same analyzers with the same arguments and the same wording: otherwise a
diagnostic "resolved" by an edit may only be a diagnostic that the replay
forgot to look for.

Every generator yields ``(level, message, path, line)`` where ``level`` is a
``logging`` method name (``"warning"`` or ``"error"``) and ``message`` carries
no location. Nothing here writes to the module.
"""

import copy
import pathlib
import re
from dataclasses import dataclass, field, replace

from .. import report, tools
from ..config import _ALLOWED_EXTENSIONS


@dataclass
class TargetIndexes:
    """Indexes of the target Odoo, plus the rule data the checks need.

    ``view_base`` / ``model_base`` index every addon except the migrated ones
    (``run_modules``); the full indexes are a copy of a base plus the migrated
    modules (:func:`compose_index`). :meth:`for_copy` composes them again with
    a temporary copy replacing one module: an index built from the original
    sources would keep the fields, views and dependencies that an edit
    removed, and hide a regression.
    """

    target_version: float
    view_index: object = None
    model_index: object = None
    import_index: object = None
    reference_modules: frozenset = frozenset()
    menu_parent_hints: list = field(default_factory=list)
    removed_fields: list = field(default_factory=list)
    view_base: object = None
    model_base: object = None
    run_modules: dict = field(default_factory=dict)
    module_rules: list = field(default_factory=list)

    @property
    def rebuilds_copies(self):
        return any(
            base is not None and index is not None
            for base, index in ((self.view_base, self.view_index), (self.model_base, self.model_index))
        )

    def for_copy(self, module_copy):
        """Indexes where ``module_copy`` (named like the original) replaces it.

        Indexes given without their base are returned unchanged.
        """
        module_copy = pathlib.Path(module_copy).resolve()
        if module_copy.name not in self.run_modules:
            return self
        view_index, model_index = self.view_index, self.model_index
        if self.view_base is not None and view_index is not None:
            view_index = compose_index(self.view_base, self.run_modules, self.module_rules, module_copy)
        if self.model_base is not None and model_index is not None:
            model_index = compose_index(self.model_base, self.run_modules, self.module_rules, module_copy)
        return replace(self, view_index=view_index, model_index=model_index)


def compose_index(base, run_modules, module_rules, replacement=None):
    """A copy of ``base`` plus the migrated modules, ``replacement`` replacing
    the module of the same name. Used both by the migration and the replay so
    that the two analyse the very same index layout."""
    index = copy.deepcopy(base)
    for name, path in run_modules.items():
        module = replacement if replacement is not None and replacement.name == name else path
        index.add_module(pathlib.Path(module))
    resolve_index_dependencies(index, module_rules)
    return index


def resolve_index_dependencies(index, module_rules):
    """Apply the merged / renamed module rules to the indexed dependencies."""
    from ..manifest import apply_module_rules

    for name, dependencies in index.depends.items():
        index.depends[name] = apply_module_rules(dependencies, module_rules)[0]


def text_rules(migration_scripts):
    """{extension: [(pattern, normalized message, level)]} of the text rules."""
    rules = {}
    for script in migration_scripts:
        script.parse_rules()
        for extension in _ALLOWED_EXTENSIONS:
            file_rules = script._file_rules(extension)
            for level, patterns in (
                ("ERROR", file_rules["errors"]),
                ("WARNING", file_rules["warnings"]),
            ):
                for pattern, message in patterns.items():
                    normalized = " ".join(message.rstrip(". ").split())
                    rules.setdefault(extension, []).append(
                        (re.compile(pattern), normalized, level)
                    )
    return rules


def text_rule_entries(module_path, rules):
    """Report entries of the text rules matching the current sources."""
    from .models import loaded_python_files

    module_path = pathlib.Path(module_path)
    loaded_python = set(loaded_python_files(module_path))
    entries = []
    for extension, extension_rules in rules.items():
        for path in tools.get_files(module_path, (extension,)):
            if extension == ".py" and path not in loaded_python:
                continue
            text = tools._read_content(path)
            for pattern, message, level in extension_rules:
                match = pattern.search(text)
                if not match:
                    continue
                source = report.SOURCE_RE.search(message)
                entry = report.Entry(
                    level,
                    message,
                    path.relative_to(module_path).as_posix(),
                    text.count("\n", 0, match.start()) + 1,
                    source.group(0) if source else "",
                )
                if entry not in entries:
                    entries.append(entry)
    return entries


def _manifest(module_path):
    return next(
        (module_path / name for name in ("__manifest__.py", "__openerp__.py")
         if (module_path / name).exists()),
        module_path / "__manifest__.py",
    )


def view_diagnostics(module_path, indexes, module_name=None):
    from . import views

    index = indexes.view_index
    if index is None:
        return
    module_path = pathlib.Path(module_path)
    name = module_name or module_path.name
    unknown = index.unknown_dependencies(name)
    if unknown:
        yield (
            "warning",
            (
                f"[incomplete] Dependencies not found in the addons paths ({', '.join(unknown)}): checks"
                " continue against available sources; risk unknown (give --context-path)"
            ),
            _manifest(module_path),
            1,
        )
    for path, line, message in views.check_module(
        module_path, index, indexes.reference_modules, indexes.menu_parent_hints,
    ):
        level = "warning" if unknown or "[incomplete]" in message else "error"
        yield level, f"[view] {message}", path, line
    for path, line, message in views.check_duplicate_fields(module_path, index):
        yield "warning", f"[view] {message}", path, line


def model_diagnostics(module_path, indexes, module_name=None):
    from . import models, python_checks

    index = indexes.model_index
    if index is None:
        return
    module_path = pathlib.Path(module_path)
    name = module_name or module_path.name
    for path, line, dependency, symbol in python_checks.manual_dependencies(module_path, index):
        if not symbol.startswith("method "):
            # Model and field dependencies are emitted by check_module below
            # with their warning severity.
            continue
        yield (
            "warning",
            (
                f"[dependency] Enterprise dependency {dependency} not added automatically; "
                f"{symbol} requires it according to the target index. Review the feature "
                "and add it explicitly if intended"
            ),
            path,
            line,
        )
    precisions = indexes.view_index.precisions if indexes.view_index is not None else None
    for path, line, level, message in python_checks.check_module(
        module_path, index, indexes.target_version,
        precision_names=precisions,
        removed_fields=indexes.removed_fields,
    ):
        yield level, message, path, line
    model_level = "warning" if index.unknown_dependencies(name) else "error"
    for path, line, message in models.check_module(module_path, index):
        yield model_level, message, path, line
    # paths of @api.depends / related= through fields that do not exist
    for path, line, message in models.check_field_paths(module_path, index):
        yield model_level, message, path, line
    for path, line, message in models.check_abstract_access(module_path, index):
        yield "warning", message, path, line
    for path, line, message in models.check_tracking_without_mail(module_path, index):
        yield "warning", message, path, line


def import_diagnostics(module_path, indexes):
    from . import imports

    if indexes.import_index is None:
        return
    for path, line, message in imports.check_module(pathlib.Path(module_path), indexes.import_index):
        yield "error", message, path, line


def access_left_diagnostics(module_path, init_version, target_version):
    if not float(init_version) < 20 <= float(target_version):
        return
    from ..upgrade_code.prepare import ACCESS_LEFT_MESSAGE, access_records_left

    for path, line in access_records_left(pathlib.Path(module_path)):
        yield "warning", ACCESS_LEFT_MESSAGE, path, line
