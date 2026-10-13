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

import ast
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
    intelligent_review: object = None

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
        circular = re.match(r"(.+?): circular dependency; (.+)", entry.message)
        if circular and entry.file and entry.line:
            try:
                tree = ast.parse(
                    (report.path / entry.file).read_text(
                        encoding="utf-8", errors="replace"
                    )
                )
                functions = [
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.lineno <= entry.line <= getattr(node, "end_lineno", node.lineno)
                ]
            except (OSError, SyntaxError, ValueError):
                functions = []
            if functions:
                function = max(functions, key=lambda node: node.lineno)
                suffix = circular[2]
                full_suffix = (
                    suffix
                    + "; keep the base hook neutral and override it in the provider or a bridge module"
                )
                prefix = f"Method {function.name} uses "
                for previous in report.entries:
                    if (
                        previous.file == entry.file
                        and previous.line == function.lineno
                        and previous.message.startswith(prefix)
                        and previous.message.endswith(full_suffix)
                    ):
                        used = previous.message[len(prefix) : -(len(full_suffix) + 2)]
                        item = circular[1]
                        if item not in used.split(", "):
                            previous.message = (
                                prefix + used + ", " + item + ": " + suffix
                            )
                        return
                entry.line = function.lineno
                entry.message = (
                    prefix
                    + circular[1]
                    + ": "
                    + full_suffix
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
    if report.intelligent_review:
        lines += render_intelligent_review(report.intelligent_review)
    return "\n".join(lines)


_STATUS_LABELS = {
    "applied": "✅ appliquée après vérification déterministe",
    "verified": "☑️ vérifiée sur copie, non publiée",
    "advice": "💬 conseil (aucune édition)",
}


def _status_label(status):
    if status in _STATUS_LABELS:
        return _STATUS_LABELS[status]
    if status.startswith("proposed"):
        return "☑️ vérifiée sur copie, non appliquée (mode revue)"
    if status.startswith("rejected"):
        return "⛔ rejetée — " + status.split(":", 1)[-1].strip()
    if status.startswith("error"):
        return "⚠️ erreur — " + status.split(":", 1)[-1].strip()
    return status


def render_intelligent_review(review):
    """Human section of the optional Ollama layer. Nothing is presented as
    verified unless the corresponding check actually ran and passed."""
    lines = ["## Assistance IA locale (Ollama)", ""]
    if review.error and not review.recommendations:
        return lines + [f"> ⚠️ Assistance indisponible : {review.error}", "",
                        "Aucune modification n'a été faite par l'IA.", ""]
    mode = getattr(review, "mode", "revue")
    lines += [
        f"> Mode : **{mode}** — modèle local `{review.model}`. Le modèle propose ; seul le migrateur",
        "> décide, après réanalyse déterministe d'une copie. Le score ci-dessous est calculé, jamais déclaré",
        "> par le modèle. Une revue Git et une installation Odoo restent nécessaires.",
        "",
    ]
    if review.error:
        lines += [f"> ⚠️ {review.error}", ""]
    if review.summary:
        lines += [review.summary, ""]
    recommendations = review.recommendations
    applied = [r for r in recommendations if r.status == "applied"]
    rejected = [r for r in recommendations if r.status.startswith(("rejected", "error"))]
    verified = [r for r in recommendations if r.status.startswith("proposed")]
    lines += [
        "| Indicateur | Valeur |",
        "|---|---|",
        f"| Éditions proposées par le modèle | {sum(1 for r in recommendations if r.old or r.operation_type)} |",
        f"| Conseils sans édition | {sum(1 for r in recommendations if r.status == 'advice')} |",
        f"| Appliquées (vérifiées puis publiées) | {len(applied)} |",
        f"| Vérifiées mais non appliquées (mode revue) | {len(verified)} |",
        f"| Rejetées par les garde-fous | {len(rejected)} |",
        f"| Durée | {review.elapsed_seconds:.1f} s |",
    ]
    session = getattr(review, "repair_session", None)
    if session is not None:
        lines += [
            (
                f"| Diagnostics rejouables avant → après | {session.initial_todos} → {session.final_todos} "
                f"(erreurs {session.initial_errors} → {session.final_errors}) |"
            ),
            f"| Diagnostics résolus et retirés de la liste TODO | {len(session.resolved)} |",
        ]
    lines.append("")
    coverage = getattr(review, "coverage", None) or []
    if coverage:
        lines += ["**Réanalyse déterministe rejouée après chaque édition :**", ""]
        for name, done, reason in coverage:
            lines.append(f"- {'✅' if done else '➖ non rejouée'} {name}" + (f" — {reason}" if reason else ""))
        lines.append("")
    for index, item in enumerate(recommendations, 1):
        lines += [f"### {index}. {item.title}", "", f"- **Décision :** {_status_label(item.status)}"]
        if item.file:
            lines.append(f"- **Emplacement :** `{item.file}" + (f":{item.line}`" if item.line else "`"))
        if item.operation_type and item.old or item.diff:
            lines.append(f"- **Opération :** `{item.operation_type}`")
        if item.diagnosis:
            lines.append(f"- **Diagnostic (selon le modèle) :** {item.diagnosis}")
        if item.action:
            lines.append(f"- **Action proposée :** {item.action}")
        if item.confidence:
            lines.append(f"- **Auto-évaluation du modèle (non prise en compte) :** {item.confidence}")
        if item.objective_score is not None:
            lines.append(
                f"- **Confiance objective :** {item.objective_confidence} — score calculé "
                f"{item.objective_score:.2f} / 1.00"
            )
        else:
            lines.append(f"- **Confiance objective :** {item.objective_confidence} (aucun score calculé)")
        if item.factors:
            lines.append("- **Facteurs du score :**")
            for factor in item.factors:
                mark = "✅" if factor.satisfied else ("⛔" if factor.mandatory else "➖")
                weight = f" (+{factor.weight:.2f})" if factor.weight else ""
                detail = f" — {factor.detail}" if factor.detail else ""
                required = " *(obligatoire)*" if factor.mandatory else ""
                lines.append(f"  - {mark} {factor.name}{weight}{required}{detail}")
        chunks = getattr(item, "evidence_chunks", None) or []
        if chunks:
            lines.append("- **Preuves vérifiées (provenance exacte) :**")
            for chunk in chunks:
                lines.append(f"  - `{chunk.provenance}` ({chunk.chunk_type}, empreinte `{chunk.fingerprint}`)")
        elif item.evidence and "réanalyse" in (item.validations or {}):
            lines.append(f"- **Références citées par le modèle, introuvables parmi les blocs montrés :** `{item.evidence}`")
        elif item.evidence:
            lines.append(f"- **Références citées (non vérifiées, rejet antérieur) :** `{item.evidence}`")
        if item.resolved:
            lines.append("- **Diagnostics résolus (réanalyse) :**")
            for file, level, message in item.resolved:
                lines.append(f"  - {level} `{file}` : {message}")
        if item.validations:
            lines.append("- **Validations :** " + ", ".join(
                f"{name} = {value}" for name, value in item.validations.items()
            ))
        if item.reason and not item.status.startswith("rejected"):
            lines.append(f"- **Motif :** {item.reason}")
        if item.diff:
            label = "Diff appliqué" if item.status == "applied" else "Diff proposé (non appliqué)"
            lines += [f"- **{label} :**", "", "```diff", *item.diff.splitlines(), "```"]
        elif item.old and item.status != "applied":
            lines += [
                "- **Remplacement proposé (non appliqué) :**", "", "```diff",
                *[f"- {line}" for line in item.old.splitlines()],
                *[f"+ {line}" for line in item.new.splitlines()],
                "```",
            ]
        lines.append("")
    manual = [r for r in recommendations if r.status != "applied"]
    if manual:
        lines += [
            (
                "**Reste manuel :** toute proposition non appliquée ci-dessus. Une édition n'est appliquée "
                "automatiquement que si elle renomme seulement des symboles, résout un diagnostic de son fichier "
                "sans en créer, et cite une règle vérifiée mentionnant l'ancien et le nouveau symbole."
            ),
            "",
        ]
    return lines


def render_summary(reports, init_version, target_version):
    lines = [
        f"# Migration {init_version} → {target_version}",
        "",
        "| Module | Risque | TODO | Erreurs | Transformations | IA locale |",
        "|---|---|---|---|---|---|",
    ]
    order = {"élevé": 0, "inconnu": 1, "moyen": 2, "faible": 3, "aucun": 4}
    for report in sorted(reports, key=lambda r: (order.get(r.risk, 99), r.name)):
        ai_status = (
            "erreur" if report.intelligent_review and report.intelligent_review.error
            else "oui" if report.intelligent_review
            else "non"
        )
        lines.append(
            f"| [{report.name}]({report.name}.md) | {report.risk} | {len(report.todos)} |"
            f" {len(report.errors)} | {len(report.transformations)} |"
            f" {ai_status} |"
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
