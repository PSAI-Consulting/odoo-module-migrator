# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Fast validation of every rule file (no Ollama, no Odoo needed).

Errors: unreadable YAML, unknown fields or enums, inconsistent versions,
invalid regex, active candidates, contradictory rules (all with file:line).
Warnings: invalid Odoo identifiers in legacy rules, hand-written rules
without justification, orphan step folders, targets absent from the Odoo
sources given with ``--odoo-source``. The audit lists the knowledge that
could become more semantic (never reclassified automatically).
"""

from __future__ import annotations

import pathlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from . import legacy, loader
from .models import Automation, Finding, OriginLayer, Rule, RuleError, RuleKind
from .ruleset import BLOCKED, RuleSet, load_rules

_MODEL_DEF_RE = re.compile(r"""^\s*_name\s*=\s*['"]([\w.]+)['"]""", re.MULTILINE)
_FIELD_DEF_RE = re.compile(r"^\s*(\w+)\s*=\s*fields\.\w+\(", re.MULTILINE)
_SIMPLE_SYMBOL_RE = re.compile(r"^(?:\\b)?([A-Za-z_][\w]*(?:\\\.[A-Za-z_]\w*)*)(?:\\b)?(?:\\\()?$")
_MOVED_RE = re.compile(r"\b(?:moved to|renamed|merged into|replaced by|now|as)\b\s+[`'\"]?([a-z0-9_]+\.[a-z0-9_.]+)",
                       re.IGNORECASE)


_NOT_FIELDS = {"removed", "renamed", "replaced", "merged", "moved", "see", "use", "the", "now", "no", "none"}


@dataclass
class SourceIndex:
    """Models, field names and modules defined in the given Odoo sources."""

    models: set[str] = field(default_factory=set)
    fields: set[str] = field(default_factory=set)
    modules: set[str] = field(default_factory=set)

    @classmethod
    def build(cls, paths) -> SourceIndex:
        index = cls()
        for base in map(pathlib.Path, paths):
            for manifest in base.glob("*/__manifest__.py"):
                index.modules.add(manifest.parent.name)
            for path in base.rglob("*.py"):
                if "tests" in path.parts:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                index.models.update(_MODEL_DEF_RE.findall(text))
                index.fields.update(_FIELD_DEF_RE.findall(text))
        return index


def _identifier_findings(rule: Rule) -> list[Finding]:
    p: Any = rule.payload
    checks = []
    if rule.kind == RuleKind.DEPRECATED_MODULE:
        checks = [("module", p.module, legacy.MODULE_RE), ("target module", p.target, legacy.MODULE_RE)]
    elif rule.kind in (RuleKind.REMOVED_MODEL, RuleKind.RENAMED_MODEL):
        checks = [("model", getattr(p, "model", None) or getattr(p, "old_model", None), legacy.MODEL_RE),
                  ("target model", getattr(p, "new_model", None) or getattr(p, "target_model", None), legacy.MODEL_RE)]
    elif rule.kind in (RuleKind.REMOVED_FIELD, RuleKind.FIELD_TYPE, RuleKind.FIELD_PROPERTY):
        checks = [("model", p.model, legacy.MODEL_RE), ("field", p.field, legacy.IDENT_RE)]
    elif rule.kind == RuleKind.RENAMED_FIELD:
        checks = [("model", p.model, legacy.MODEL_RE), ("field", p.old_field, legacy.IDENT_RE),
                  ("new field", p.new_field, legacy.IDENT_RE)]
    elif rule.kind == RuleKind.RENAMED_METHOD:
        checks = [("model", p.model, legacy.MODEL_RE), ("method", p.old_method, legacy.IDENT_RE),
                  ("new method", p.new_method, legacy.IDENT_RE)]
    elif rule.kind == RuleKind.MENU_PARENT_HINT:
        checks = [("menu", v, legacy.XMLID_RE) for v in (p.removed_parent, p.surviving_child, p.candidate_parent)]
    level = "error" if rule.structured else "warning"
    return [
        Finding(level, "invalid_identifier", f"{label} {value!r} is not a valid Odoo identifier", rule.origin.ref,
                (rule.stable_id,))
        for label, value, regex in checks if value is not None and not regex.fullmatch(value)
    ]


def _justified(rule: Rule) -> bool:
    return bool(rule.evidence)


def _target_findings(rule: Rule, index: SourceIndex) -> list[Finding]:
    p: Any = rule.payload
    missing = []
    if rule.kind == RuleKind.RENAMED_MODEL and index.models and p.new_model not in index.models:
        missing.append(f"model {p.new_model}")
    if rule.kind == RuleKind.REMOVED_MODEL and index.models:
        if p.target_model and p.target_model not in index.models:
            missing.append(f"model {p.target_model}")
        if p.model in index.models:
            missing.append(f"model {p.model} still defined (not removed?)")
    if rule.kind == RuleKind.RENAMED_FIELD and index.fields and not p.is_blocker \
            and legacy.IDENT_RE.fullmatch(p.new_field or "") and p.new_field not in index.fields:
        missing.append(f"field {p.new_field}")
    if rule.kind == RuleKind.DEPRECATED_MODULE and index.modules and p.target and p.target not in index.modules:
        missing.append(f"module {p.target}")
    return [Finding("warning", "missing_target", f"{m} not found in the Odoo sources", rule.origin.ref,
                    (rule.stable_id,)) for m in missing]


def check_files(root: pathlib.Path | None = None) -> list[Finding]:
    """Errors of each rule file, one by one (load_rules stops at the first)."""
    root = pathlib.Path(root or loader.SCRIPTS_DIR)
    findings = []
    for category in legacy.LOAD_ORDER:
        for step in loader.step_names(category, root):
            try:
                from .models import Step
                Step.parse(step)
            except RuleError as exc:
                findings.append(Finding("error", "invalid_step", str(exc), f"{category}/{step}"))
                continue
            for path in loader.rule_files(category, step, root):
                try:
                    loader.load_file(path, category, root)
                except RuleError as exc:
                    findings.append(Finding("error", "invalid_rule", str(exc), exc.where))
    return findings


@dataclass
class Report:
    ruleset: RuleSet | None
    findings: list[Finding]
    audit: dict[str, list[str]] = field(default_factory=dict)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]


def validate(root=None, odoo_sources=(), with_python: bool = True) -> Report:
    findings = check_files(root)
    if any(f.level == "error" for f in findings):
        return Report(None, findings)
    ruleset = load_rules(root, python=with_python)
    findings += ruleset.findings
    index = SourceIndex.build(odoo_sources) if odoo_sources else None
    for rule in ruleset.rules:
        findings += _identifier_findings(rule)
        if rule.origin_layer == OriginLayer.CURATED and not _justified(rule):
            findings.append(Finding("warning", "unjustified_curated",
                                    "hand-written rule without source, message or comment", rule.origin.ref,
                                    (rule.stable_id,)))
        if index and ruleset.effective(rule):
            findings += _target_findings(rule, index)
    return Report(ruleset, findings, audit(ruleset))


def audit(ruleset: RuleSet) -> dict[str, list[str]]:
    """Knowledge that could become more semantic. Suggestions only: a rule is
    reclassified by hand, with an evidence from the sources or a commit."""
    result: dict[str, list[str]] = defaultdict(list)
    for rule in ruleset.rules:
        if not ruleset.effective(rule):
            continue
        p: Any = rule.payload
        ref = rule.origin.ref
        if rule.kind == RuleKind.REMOVED_MODEL:
            match = _MOVED_RE.search(p.message or "")
            if match and not rule.structured:
                result["removed_models_with_successor"].append(f"{ref} {p.model} -> {match.group(1)}")
        elif rule.kind == RuleKind.REMOVED_FIELD:
            match = re.match(r"^\s*([a-z_][a-z0-9_]*)\b(?!\.)", p.message or "")
            if match and rule.origin_layer == OriginLayer.CURATED and "OpenUpgrade" not in (p.message or ""):
                result["removed_fields_with_replacement"].append(f"{ref} {p.model}.{p.field} -> {match.group(1)}?")
        elif rule.kind == RuleKind.DEPRECATED_MODULE and str(p.change) == "removed":
            comments = " ".join(e.text for e in rule.evidence)
            if re.search(r"\[(?:MOV|MERGE)\]|\bmerge", comments, re.IGNORECASE):
                result["removed_modules_maybe_merged"].append(f"{ref} {p.module}: {comments[:120]}")
        elif rule.kind in (RuleKind.TEXT_ERROR, RuleKind.TEXT_WARNING) and _SIMPLE_SYMBOL_RE.match(p.pattern):
            result["regex_rules_on_a_single_symbol"].append(f"{ref} {p.extension} {p.pattern}")
        elif rule.kind == RuleKind.PYTHON_TRANSFORM and not rule.preconditions and not rule.structured:
            result["python_transforms_without_declared_conditions"].append(
                f"{ref} {p.module.rsplit('.', 1)[-1]}.{p.function}")
        if not rule.structured and rule.evidence and all(
                getattr(e, "location", "") in ("comment", "group_comment", "inline_comment") for e in rule.evidence):
            result["evidence_only_in_comments"].append(f"{ref} {rule.kind}")
    return dict(result)


def summary(report: Report, step: str | None = None) -> str:
    ruleset = report.ruleset
    lines = []
    if ruleset is None:
        lines.append("Rules not loaded (file errors below)")
    else:
        by_step: dict[str, list[Rule]] = defaultdict(list)
        for rule in ruleset.rules:
            by_step[rule.step.name].append(rule)
        conflicts = Counter(f.where.split(":")[0].split("/")[1] if "/" in f.where else "" for f in report.errors)
        for name in sorted(by_step, key=lambda s: (by_step[s][0].step.from_code or 0, s)):
            if step and name != step:
                continue
            rules = by_step[name]
            lines.append(f"{rules[0].step.label} [{name}]" + ("  (ORPHAN: never loaded)" if name in ruleset.orphan_steps else ""))
            for kind in RuleKind:
                same = [r for r in rules if r.kind == kind]
                if not same:
                    continue
                layers = Counter(r.origin_layer.value for r in same)
                extra = []
                blockers = sum(r.automation == Automation.BLOCKER for r in same)
                if blockers:
                    extra.append(f"{blockers} blockers")
                status = Counter(ruleset.resolutions[r.stable_id].status for r in same)
                extra += [f"{n} {s}" for s, n in sorted(status.items()) if s != "effective" and s != BLOCKED]
                if status.get(BLOCKED):
                    extra.append(f"{status[BLOCKED]} generated blocked")
                lines.append(f"  {kind}: " + ", ".join(f"{n} {layer}" for layer, n in sorted(layers.items()))
                             + (f" ({', '.join(extra)})" if extra else ""))
            structured = sum(r.structured for r in rules)
            missing = sum(not r.evidence for r in rules if r.kind != RuleKind.PYTHON_TRANSFORM)
            lines.append(f"  conflicts: {conflicts.get(name, 0)}  legacy rules: {len(rules) - structured}  "
                         f"structured rules: {structured}  missing evidence: {missing}")
    levels = Counter(f.level for f in report.findings)
    codes = Counter((f.level, f.code) for f in report.findings)
    lines.append(f"findings: {levels.get('error', 0)} error(s), {levels.get('warning', 0)} warning(s)")
    for (level, code), count in sorted(codes.items()):
        lines.append(f"  {level} {code}: {count}")
    return "\n".join(lines)
