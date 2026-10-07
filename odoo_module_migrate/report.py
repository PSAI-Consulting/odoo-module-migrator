# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Per module migration report (MIGRATION_REPORT.md).

The log records emitted during the migration are collected and attached to a
module: through the path they mention (``File <path>:<line>``, ``in <path>``...)
or, failing that, the module being migrated. Each module gets:

* the transformations applied (INFO);
* the manual TODO list (WARNING / ERROR) with ``file:line`` and the source;
* the dependencies removed or replaced;
* the files modified;
* a risk level.
"""

import collections
import logging
import pathlib
import re
from dataclasses import dataclass, field

REPORT_NAME = "MIGRATION_REPORT.md"

SOURCE_RE = re.compile(
    r"(https?://\S+?)(?=[\s)\]'\",]|$)"
    r"|\b(?:odoo|enterprise|design-themes)\s+[0-9a-f]{7,40}\b(?:\s+'[^']*')?"
    r"|OpenUpgrade\s+\d+\.\d+\s+\S+"
)
# "[module] Running migration from 19.0 to 20.0" (module_migration.py)
RUNNING_RE = re.compile(r"\[[\w.]+\] Running migration ")
LEVELS = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 2}


@dataclass
class Entry:
    level: str
    message: str
    file: str = ""
    line: int = 0
    source: str = ""


@dataclass
class ModuleReport:
    name: str
    path: pathlib.Path
    entries: list = field(default_factory=list)

    @property
    def todos(self):
        return [e for e in self.entries if LEVELS.get(e.level, 0) >= 1]

    @property
    def errors(self):
        return [e for e in self.entries if LEVELS.get(e.level, 0) >= 2]

    @property
    def depends(self):
        return [e for e in self.entries if e.message.startswith(("Dependency", "Depends on"))]

    @property
    def transformations(self):
        return [
            e for e in self.entries
            if e.level == "INFO" and not e.message.startswith(("Dependency", "Running", "Migrate "))
            and not RUNNING_RE.match(e.message)
        ]

    @property
    def risk(self):
        if self.errors:
            return "élevé"
        if any("[incomplete]" in e.message for e in self.entries):
            return "inconnu"
        if len(self.todos) > 5:
            return "moyen"
        if self.todos:
            return "faible"
        return "aucun"


class ReportCollector(logging.Handler):
    """Logging handler dispatching the records to the module reports."""

    def __init__(self, modules):
        super().__init__(logging.INFO)
        self.reports = {
            name: ModuleReport(name, pathlib.Path(path).resolve()) for name, path in modules
        }
        # longest paths first: a module path may be the prefix of another one
        self._paths = sorted(
            ((str(r.path), r) for r in self.reports.values()), key=lambda x: -len(x[0])
        )
        self.current = None

    def _locate(self, message):
        """(report, relative file, line, message without the location)."""
        lowered = message.replace("/", "\\").lower()
        for path, report in self._paths:
            key = path.replace("/", "\\").lower()
            index = lowered.find(key)
            if index < 0:
                continue
            match = re.compile(r"[\\/]([^\s:'\",)]+)(?::(\d+))?").match(message, index + len(path))
            relative = match.group(1).replace("\\", "/") if match else ""
            line = int(match.group(2)) if match and match.group(2) else 0
            cleaned = message[:index] + message[match.end() if match else index + len(path):]
            cleaned = re.sub(
                r"\s*(?:\.\s*)?\b(?:File|in file|in)\s*:?\s*$", "", cleaned.strip()
            )
            return report, relative, line, cleaned.strip(" .\n") or message
        return self.current, "", 0, message

    def emit(self, record):
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            return
        report, relative, line, cleaned = self._locate(message)
        if report is None:
            return
        source = SOURCE_RE.search(cleaned)
        entry = Entry(
            record.levelname, " ".join(cleaned.split()), relative, line,
            source.group(0) if source else "",
        )
        # the same rule may be reported by several version steps
        if entry not in report.entries:
            report.entries.append(entry)


def _location(entry):
    if not entry.file:
        return ""
    target = entry.file + (f"#L{entry.line}" if entry.line else "")
    label = entry.file + (f":{entry.line}" if entry.line else "")
    return f"[`{label}`]({target})"


def render(report, init_version, target_version, changed_files=()):
    lines = [
        f"# Migration de `{report.name}` : {init_version} → {target_version}",
        "",
        "Rapport généré par odoo-module-migrator. Les TODO sont à traiter à la main ;"
        " cochez-les au fur et à mesure.",
        "",
        "| Risque | TODO | dont erreurs | Transformations | Fichiers modifiés |",
        "|---|---|---|---|---|",
        f"| **{report.risk}** | {len(report.todos)} | {len(report.errors)} |"
        f" {len(report.transformations)} | {len(changed_files)} |",
        "",
    ]
    if report.depends:
        lines += ["## Dépendances", ""]
        lines += [f"- {e.message}" for e in report.depends] + [""]
    lines += ["## TODO manuels", ""]
    if not report.todos:
        lines += ["Aucun.", ""]
    by_file = collections.defaultdict(list)
    for entry in report.todos:
        by_file[entry.file].append(entry)
    for file_name in sorted(by_file, key=lambda f: (f == "", f)):
        lines.append(f"### {file_name or 'Module'}")
        lines.append("")
        seen = set()
        for entry in sorted(by_file[file_name], key=lambda e: (-LEVELS.get(e.level, 0), e.line)):
            key = (entry.message, entry.line)
            if key in seen:
                continue
            seen.add(key)
            badge = "🔴 erreur" if LEVELS.get(entry.level, 0) >= 2 else "🟠 à vérifier"
            location = _location(entry)
            lines.append(f"- [ ] {badge} {location + ' : ' if location else ''}{entry.message}")
        lines.append("")
    lines += ["## Transformations appliquées", ""]
    seen = set()
    for entry in report.transformations:
        text = (f"{_location(entry)} : " if entry.file else "") + entry.message
        if text not in seen:
            seen.add(text)
            lines.append(f"- {text}")
    if not seen:
        lines.append("Aucune.")
    lines.append("")
    if changed_files:
        lines += ["## Fichiers modifiés", ""]
        lines += [f"- `{f}`" for f in sorted(changed_files)] + [""]
    return "\n".join(lines)


def render_summary(reports, init_version, target_version):
    lines = [
        f"# Migration {init_version} → {target_version}",
        "",
        "| Module | Risque | TODO | Erreurs | Transformations |",
        "|---|---|---|---|---|",
    ]
    order = {"élevé": 0, "moyen": 1, "faible": 2, "aucun": 3}
    for report in sorted(reports, key=lambda r: (order[r.risk], r.name)):
        lines.append(
            f"| [{report.name}]({report.name}.md) | {report.risk} | {len(report.todos)} |"
            f" {len(report.errors)} | {len(report.transformations)} |"
        )
    # most frequent TODO: what to handle once for all the modules
    modules_by_todo = collections.defaultdict(set)
    level_by_todo = {}
    for report in reports:
        for entry in report.todos:
            key = _todo_key(entry.message)
            modules_by_todo[key].add(report.name)
            level_by_todo[key] = max(level_by_todo.get(key, 0), LEVELS.get(entry.level, 0))
    if modules_by_todo:
        lines += [
            "",
            "## TODO les plus fréquents",
            "",
            "| Modules | Niveau | TODO |",
            "|---|---|---|",
        ]
        ranked = sorted(modules_by_todo.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        for key, modules in ranked[:30]:
            level = "erreur" if level_by_todo[key] >= 2 else "à vérifier"
            lines.append(f"| {len(modules)} | {level} | {key.replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def _todo_key(message):
    """Message without what is specific to one place (the context of a field
    usage, the field of a view anchor...), to group the same change."""
    message = re.sub(r"\s*\((?:self|rec|record|[a-z_]+)\.\w+\)|\s*\(\.\w+\(\{?\[?\.\.\.\]?\}?\)\)", "", message)
    message = re.sub(r"\s*\((?:@api\.\w+|<record model=[\w.]+>|view of [\w.]+|xpath of a view of [\w.]+|related=)\)", "", message)
    return message.strip()
