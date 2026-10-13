# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Deterministic replay of the module diagnostics on a temporary copy.

The replay runs the very analyzers of the migration (shared with
:mod:`odoo_module_migrate.analysis.module_diagnostics`) and formats their
findings through a private :class:`~odoo_module_migrate.report.ReportCollector`,
so a replayed diagnostic is worded exactly like the report entry it stands for.

Two rules make the comparison trustworthy:

* fail closed: an analyzer raising an exception raises
  :class:`DiagnosticsUnavailable`; it is never turned into a diagnostic that
  could "disappear" after an edit;
* line independence: diagnostics are compared as a multiset of
  ``(file, level, message)``. Inserting an import shifts every following line
  without resolving or creating anything.
"""

from __future__ import annotations

import ast
import collections
import csv
import io
import logging
import pathlib
from dataclasses import dataclass
from typing import Any

from lxml import etree

from .. import report, tools
from ..analysis import module_diagnostics

logger = logging.getLogger(__name__)

_MANIFEST_NAMES = ("__manifest__.py", "__openerp__.py")


class DiagnosticsUnavailable(RuntimeError):
    """An analyzer failed: the module state cannot be proven either way."""


@dataclass(frozen=True)
class DiagnosticItem:
    level: str  # ERROR, WARNING, INFO
    message: str
    file: str = ""
    line: int = 0
    source: str = ""
    rule_id: str = ""

    def stable_id(self) -> str:
        return stable_diagnostic_id(self)


def diagnostic_key(item: Any) -> tuple[str, str, str]:
    """Line-independent identity of a diagnostic: (file, level, message)."""
    if isinstance(item, dict):
        file, level, message = item.get("file", ""), item.get("level", "WARNING"), item.get("message", "")
    else:
        file = getattr(item, "file", "")
        level = getattr(item, "level", "WARNING")
        message = getattr(item, "message", str(item))
    return (
        str(file or "").replace("\\", "/").strip(),
        str(level or "WARNING").strip().upper(),
        " ".join(str(message or "").strip().split()),
    )


def stable_diagnostic_id(item: Any) -> str:
    """Printable form of :func:`diagnostic_key` (no line number)."""
    return "{}:{}:{}".format(*diagnostic_key(item))


@dataclass
class DiagnosticDelta:
    resolved: collections.Counter
    added: collections.Counter

    @property
    def resolved_count(self) -> int:
        return sum(self.resolved.values())

    @property
    def added_count(self) -> int:
        return sum(self.added.values())


def compare_diagnostics(before: list[Any], after: list[Any]) -> DiagnosticDelta:
    """Multiset difference: a line move is neither resolved nor added."""
    old = collections.Counter(diagnostic_key(d) for d in before)
    new = collections.Counter(diagnostic_key(d) for d in after)
    return DiagnosticDelta(resolved=old - new, added=new - old)


def _entries_from_logged(module_path: pathlib.Path, name: str, findings) -> list[report.Entry]:
    """Format (level, message, path, line) exactly like the migration report."""
    collector = report.ReportCollector([(name, module_path)])
    module_report = collector.reports[name]
    collector.current = module_report
    for level, message, path, line in findings:
        record = logging.LogRecord(
            "odoo_module_migrate", getattr(logging, level.upper()), __file__, 0,
            "%s. File %s:%s", (message, path, line), None,
        )
        collector.emit(record)
    return list(module_report.entries)


class FullModuleDiagnosticsChecker:
    """Replays the deterministic diagnostics of one module on any copy of it.

    ``indexes`` is the :class:`TargetIndexes` of the migration. When it carries
    build paths, the view and model indexes are rebuilt for each copy so that
    the copy's own fields, views and dependencies are the ones checked.
    """

    def __init__(
        self,
        target_version: str,
        migration_scripts: list[Any] | None = None,
        model_index: Any | None = None,
        view_index: Any | None = None,
        import_index: Any | None = None,
        *,
        indexes: module_diagnostics.TargetIndexes | None = None,
        init_version: str | None = None,
        module_name: str | None = None,
    ):
        self.target_version = target_version
        self.init_version = init_version
        self.module_name = module_name
        self.migration_scripts = migration_scripts or []
        if indexes is None and (model_index is not None or view_index is not None or import_index is not None):
            indexes = module_diagnostics.TargetIndexes(
                float(target_version),
                view_index=view_index,
                model_index=model_index,
                import_index=import_index,
            )
        self.indexes = indexes
        self._rules = None

    def coverage(self) -> list[tuple[str, bool, str]]:
        """(analysis, replayed, reason) for the human report."""
        indexes = self.indexes
        has = {
            "views": indexes is not None and indexes.view_index is not None,
            "models": indexes is not None and indexes.model_index is not None,
            "imports": indexes is not None and indexes.import_index is not None,
        }
        rebuilt = bool(indexes is not None and indexes.rebuilds_copies)
        no_sources = "sources de la version cible non indexées (pas d'upgrade_code / --addons-path)"
        rows = [
            ("syntaxe Python / XML / CSV et manifeste", True, ""),
            ("règles textuelles du migrateur", bool(self.migration_scripts),
             "" if self.migration_scripts else "aucun script de migration fourni"),
            ("vues, XPath, XML ids et menus", has["views"], "" if has["views"] else no_sources),
            ("modèles, champs, méthodes, dépendances Python", has["models"], "" if has["models"] else no_sources),
            ("imports depuis les addons cibles", has["imports"], "" if has["imports"] else no_sources),
            ("index reconstruits sur la copie", rebuilt or not (has["views"] or has["models"]),
             "" if rebuilt or not (has["views"] or has["models"]) else "index fournis tels quels (copie non réindexée)"),
        ]
        if self.init_version:
            rows.append(("enregistrements ir.model.access / ir.rule restants", True, ""))
        rows.append((
            "diagnostics émis pendant les scripts de transformation", False,
            "non rejouables sans relancer la migration : jamais comptés comme résolus",
        ))
        return rows

    def _text_rules(self):
        if self._rules is None:
            self._rules = module_diagnostics.text_rules(self.migration_scripts)
        return self._rules

    def check_module(self, module_path: pathlib.Path | str) -> list[report.Entry]:
        """All replayable diagnostics of the module; raises DiagnosticsUnavailable."""
        module_path = pathlib.Path(module_path).resolve()
        name = self.module_name or module_path.name
        if module_path.name != name:
            raise DiagnosticsUnavailable(
                f"la copie {module_path} ne porte pas le nom du module {name!r} : "
                "les index ne la reconnaîtraient pas"
            )
        try:
            entries = self._syntax_entries(module_path)
            if self.migration_scripts:
                entries += module_diagnostics.text_rule_entries(module_path, self._text_rules())
            findings = []
            if self.indexes is not None:
                indexes = self.indexes.for_copy(module_path)
                findings += module_diagnostics.view_diagnostics(module_path, indexes, name)
                findings += module_diagnostics.model_diagnostics(module_path, indexes, name)
                findings += module_diagnostics.import_diagnostics(module_path, indexes)
            if self.init_version:
                findings += module_diagnostics.access_left_diagnostics(
                    module_path, self.init_version, self.target_version
                )
            entries += _entries_from_logged(module_path, name, findings)
        except DiagnosticsUnavailable:
            raise
        except Exception as exc:  # fail closed, never a "resolved" diagnostic
            logger.debug("Diagnostics replay failed on %s", module_path, exc_info=True)
            raise DiagnosticsUnavailable(
                f"analyse déterministe impossible ({type(exc).__name__}: {exc})"
            ) from exc
        return entries

    def _syntax_entries(self, module_path: pathlib.Path) -> list[report.Entry]:
        entries = []
        manifest_path = next(
            (module_path / name for name in _MANIFEST_NAMES if (module_path / name).is_file()),
            None,
        )
        if not manifest_path:
            entries.append(report.Entry("ERROR", "No manifest file found (__manifest__.py)", "__manifest__.py", 1))
        else:
            try:
                manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8").lstrip())
                if not isinstance(manifest, dict):
                    entries.append(report.Entry(
                        "ERROR", "Manifest must evaluate to a dictionary", manifest_path.name, 1
                    ))
            except (SyntaxError, ValueError) as exc:
                entries.append(report.Entry("ERROR", f"Invalid manifest syntax: {exc}", manifest_path.name, 1))
        for ext in (".py", ".xml", ".csv"):
            for path in tools.get_files(module_path, (ext,)):
                rel = path.relative_to(module_path).as_posix()
                content = tools._read_content(path)
                try:
                    if ext == ".py":
                        ast.parse(content, filename=str(path))
                    elif ext == ".xml":
                        etree.fromstring(content.encode("utf-8"), parser=etree.XMLParser(recover=False))
                    else:
                        list(csv.reader(io.StringIO(content)))
                except SyntaxError as exc:
                    entries.append(report.Entry("ERROR", f"Python syntax error: {exc.msg}", rel, exc.lineno or 1))
                except etree.XMLSyntaxError as exc:
                    entries.append(report.Entry("ERROR", f"XML syntax error: {exc.msg}", rel, exc.lineno or 1))
                except csv.Error as exc:
                    entries.append(report.Entry("ERROR", f"CSV syntax error: {exc}", rel, 1))
        return entries
