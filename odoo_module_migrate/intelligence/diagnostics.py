# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Deterministic full-module diagnostic runner and stable ID tracking.

Executes a complete verification suite across Python, XML, CSV, manifests,
models, views, and text migration rules. Never relies on partial regex heuristics
or simulated counters.
"""

from __future__ import annotations

import ast
import csv
import io
import logging
import pathlib
import re
from dataclasses import dataclass
from typing import Any

from lxml import etree

from .. import report, tools

logger = logging.getLogger(__name__)
_ALLOWED_EXTENSIONS = (".py", ".xml", ".csv", ".js")


@dataclass(frozen=True)
class DiagnosticItem:
    level: str  # ERROR, WARNING, INFO
    message: str
    file: str = ""
    line: int = 0
    source: str = ""
    rule_id: str = ""

    def stable_id(self) -> str:
        """Stable, canonical identifier for regression and resolution checks."""
        norm_file = self.file.replace("\\", "/").strip()
        norm_msg = " ".join(self.message.strip().split())
        return f"{norm_file}:{self.line}:{self.level}:{norm_msg}"


def stable_diagnostic_id(item: Any) -> str:
    """Extract or compute a stable diagnostic identifier from any item."""
    if isinstance(item, DiagnosticItem):
        return item.stable_id()
    if isinstance(item, report.Entry):
        norm_file = item.file.replace("\\", "/").strip()
        norm_msg = " ".join(item.message.strip().split())
        return f"{norm_file}:{item.line}:{item.level}:{norm_msg}"
    if isinstance(item, dict):
        norm_file = str(item.get("file", "")).replace("\\", "/").strip()
        line = int(item.get("line", 0) or 0)
        level = str(item.get("level", "WARNING")).strip()
        norm_msg = " ".join(str(item.get("message", "")).strip().split())
        return f"{norm_file}:{line}:{level}:{norm_msg}"
    return str(item)


_MANIFEST_NAMES = ("__manifest__.py", "__openerp__.py")


class FullModuleDiagnosticsChecker:
    """Runs a full, deterministic analysis suite on a target module directory."""

    def __init__(
        self,
        target_version: str,
        migration_scripts: list[Any] | None = None,
        model_index: Any | None = None,
        view_index: Any | None = None,
        import_index: Any | None = None,
    ):
        self.target_version = target_version
        self.migration_scripts = migration_scripts or []
        self.model_index = model_index
        self.view_index = view_index
        self.import_index = import_index

    def check_module(self, module_path: pathlib.Path | str) -> list[DiagnosticItem]:
        """Run full syntax, structure, rules, and semantic checks on the module."""
        module_path = pathlib.Path(module_path).resolve()
        diagnostics: list[DiagnosticItem] = []

        # 1. Manifest verification
        manifest_path = next(
            (module_path / name for name in _MANIFEST_NAMES if (module_path / name).is_file()),
            None,
        )
        if not manifest_path:
            diagnostics.append(DiagnosticItem(
                level="ERROR",
                message="No manifest file found (__manifest__.py)",
                file="__manifest__.py",
                line=1,
            ))
        else:
            try:
                m_content = manifest_path.read_text(encoding="utf-8")
                m_dict = ast.literal_eval(m_content)
                if not isinstance(m_dict, dict):
                    diagnostics.append(DiagnosticItem(
                        level="ERROR",
                        message="Manifest must evaluate to a dictionary",
                        file=manifest_path.name,
                        line=1,
                    ))
            except Exception as exc:  # noqa: BLE001
                diagnostics.append(DiagnosticItem(
                    level="ERROR",
                    message=f"Invalid manifest syntax: {exc}",
                    file=manifest_path.name,
                    line=1,
                ))

        # 2. Syntax verification on all files
        for ext in (".py", ".xml", ".csv"):
            for p in tools.get_files(module_path, (ext,)):
                rel_p = p.relative_to(module_path).as_posix()
                try:
                    content = tools._read_content(p)
                    if ext == ".py":
                        ast.parse(content, filename=str(p))
                    elif ext == ".xml":
                        etree.fromstring(content.encode("utf-8"), parser=etree.XMLParser(recover=False))
                    elif ext == ".csv":
                        list(csv.reader(io.StringIO(content)))
                except SyntaxError as exc:
                    diagnostics.append(DiagnosticItem(
                        level="ERROR",
                        message=f"Python syntax error: {exc.msg}",
                        file=rel_p,
                        line=exc.lineno or 1,
                    ))
                except etree.XMLSyntaxError as exc:
                    diagnostics.append(DiagnosticItem(
                        level="ERROR",
                        message=f"XML syntax error: {exc}",
                        file=rel_p,
                        line=getattr(exc, "lineno", 1) or 1,
                    ))
                except csv.Error as exc:
                    diagnostics.append(DiagnosticItem(
                        level="ERROR",
                        message=f"CSV syntax error: {exc}",
                        file=rel_p,
                        line=1,
                    ))

        # 3. Text rules re-evaluation
        rules: dict[str, list[tuple[re.Pattern, str, str]]] = {}
        for script in self.migration_scripts:
            if hasattr(script, "parse_rules"):
                script.parse_rules()
            for extension in _ALLOWED_EXTENSIONS:
                if hasattr(script, "_file_rules"):
                    file_rules = script._file_rules(extension)
                    for level, patterns in (
                        ("ERROR", file_rules.get("errors", {})),
                        ("WARNING", file_rules.get("warnings", {})),
                    ):
                        for pattern, msg in patterns.items():
                            norm = " ".join(msg.rstrip(". ").split())
                            rules.setdefault(extension, []).append(
                                (re.compile(pattern), norm, level)
                            )

        for ext, ext_rules in rules.items():
            for p in tools.get_files(module_path, (ext,)):
                rel_p = p.relative_to(module_path).as_posix()
                try:
                    text = tools._read_content(p)
                except OSError:
                    continue
                for pattern, msg, level in ext_rules:
                    match = pattern.search(text)
                    if match:
                        line_no = text.count("\n", 0, match.start()) + 1
                        diagnostics.append(DiagnosticItem(
                            level=level,
                            message=msg,
                            file=rel_p,
                            line=line_no,
                        ))

        # 4. View and XPath checks if view_index available
        if self.view_index:
            try:
                from ..analysis import views
                for p, line, msg in views.check_module(module_path, self.view_index):
                    rel_p = pathlib.Path(p).relative_to(module_path).as_posix() if pathlib.Path(p).is_absolute() else str(p)
                    diagnostics.append(DiagnosticItem(
                        level="ERROR" if "[incomplete]" not in msg else "WARNING",
                        message=msg,
                        file=rel_p,
                        line=line,
                    ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("View diagnostics check failure: %s", exc)
                diagnostics.append(DiagnosticItem(
                    level="ERROR",
                    message=f"Échec de l'analyse interne des vues ({type(exc).__name__}: {exc})",
                    file="__diagnostic_failure__",
                    line=1,
                ))

        # 5. Model and Python callbacks if model_index available
        if self.model_index:
            try:
                from ..analysis import models, python_checks
                for p, line, level, msg in python_checks.check_module(
                    module_path, self.model_index, float(self.target_version)
                ):
                    rel_p = pathlib.Path(p).relative_to(module_path).as_posix() if pathlib.Path(p).is_absolute() else str(p)
                    diagnostics.append(DiagnosticItem(
                        level=level,
                        message=msg,
                        file=rel_p,
                        line=line,
                    ))
                for p, line, msg in models.check_module(module_path, self.model_index):
                    rel_p = pathlib.Path(p).relative_to(module_path).as_posix() if pathlib.Path(p).is_absolute() else str(p)
                    diagnostics.append(DiagnosticItem(
                        level="ERROR",
                        message=msg,
                        file=rel_p,
                        line=line,
                    ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Model diagnostics check failure: %s", exc)
                diagnostics.append(DiagnosticItem(
                    level="ERROR",
                    message=f"Échec de l'analyse interne des modèles ({type(exc).__name__}: {exc})",
                    file="__diagnostic_failure__",
                    line=1,
                ))

        # 6. Import checks if import_index available
        if self.import_index:
            try:
                from ..analysis import imports
                for p, line, msg in imports.check_module(module_path, self.import_index):
                    rel_p = pathlib.Path(p).relative_to(module_path).as_posix() if pathlib.Path(p).is_absolute() else str(p)
                    diagnostics.append(DiagnosticItem(
                        level="ERROR",
                        message=msg,
                        file=rel_p,
                        line=line,
                    ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Import diagnostics check failure: %s", exc)
                diagnostics.append(DiagnosticItem(
                    level="ERROR",
                    message=f"Échec de l'analyse interne des imports ({type(exc).__name__}: {exc})",
                    file="__diagnostic_failure__",
                    line=1,
                ))

        return diagnostics
