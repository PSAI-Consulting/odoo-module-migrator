# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""All the rules of ``migration_scripts`` with their precedence resolved.

The resolution only *describes* what the historical semantics already do; it
never changes the data consumed by the migration scripts:

* list rules (fields, models, modules...): the first rule loaded wins
  (curated.yaml before generated.yaml), a curated ``[model, field, null]`` or
  same-name rename blocks a generated rename, a renamed field is not removed;
* text rules: a later file overrides an earlier one (``dict.update``);
* a step folder that no ``migrate_*.py`` loads is inactive (orphan).

Anything else (two different hand-written answers for the same key, a
removed module that a later rule renames...) is a conflict: a validation
error, never a silent choice.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import pathlib
from collections import defaultdict
from dataclasses import dataclass, field

from . import legacy, loader
from .models import (
    ChangeKind,
    Finding,
    OriginLayer,
    Rule,
    RuleKind,
    Step,
)

EFFECTIVE = "effective"
SUPERSEDED = "superseded"  # curated replaces a generated rule
BLOCKED = "blocked"  # curated null / same-name rename blocks a generated rename
DUPLICATE = "duplicate"  # same historical value as the winning rule
SHADOWED_BY_RENAME = "renamed"  # removed field that a rename handles
CONFLICT = "conflict"
INACTIVE = "inactive"  # orphan step folder, never loaded

TEXT_KINDS = {RuleKind.TEXT_REPLACE, RuleKind.TEXT_ERROR, RuleKind.TEXT_WARNING}


@dataclass(frozen=True)
class Resolution:
    status: str
    by: str = ""  # stable id of the rule that wins over this one
    reason: str = ""

    @property
    def effective(self) -> bool:
        return self.status == EFFECTIVE


@dataclass
class RuleSet:
    rules: list[Rule]
    resolutions: dict[str, Resolution]
    findings: list[Finding] = field(default_factory=list)
    orphan_steps: list[str] = field(default_factory=list)
    signature: str = ""

    def by_id(self) -> dict[str, Rule]:
        return {r.stable_id: r for r in self.rules}

    def for_step(self, step: str) -> list[Rule]:
        return [r for r in self.rules if r.step.name == step]

    def effective(self, rule: Rule) -> bool:
        return self.resolutions[rule.stable_id].effective

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]


def _resolve_list(rules: list[Rule], resolutions: dict, findings: list) -> None:
    winners: dict[tuple, Rule] = {}
    for rule in rules:
        key = (rule.kind, rule.key)
        first = winners.get(key)
        if first is None:
            winners[key] = rule
            resolutions[rule.stable_id] = Resolution(EFFECTIVE)
            continue
        if rule.legacy == first.legacy:
            reason = "identical rule" if rule.origin_layer == first.origin_layer else \
                f"same rule in {first.origin_layer}"
            resolutions[rule.stable_id] = Resolution(DUPLICATE, first.stable_id, reason)
            continue
        if first.kind == RuleKind.DEPRECATED_MODULE and first.payload.change == ChangeKind.REMOVED:
            # apply_module_rules keeps a "removed" dependency: the later rule
            # would still rename it, both apply
            resolutions[rule.stable_id] = Resolution(CONFLICT, first.stable_id, "removed then changed again")
            findings.append(Finding("error", "removed_then_changed", (
                f"module {rule.key[0]}: {first.origin.ref} says removed but {rule.origin.ref} still applies"),
                rule.origin.ref, (first.stable_id, rule.stable_id)))
            continue
        if first.origin_layer == OriginLayer.CURATED and rule.origin_layer == OriginLayer.GENERATED:
            if first.kind == RuleKind.RENAMED_FIELD and first.payload.is_blocker:
                resolutions[rule.stable_id] = Resolution(BLOCKED, first.stable_id, "curated blocks the rename")
            else:
                resolutions[rule.stable_id] = Resolution(SUPERSEDED, first.stable_id, "curated replaces generated")
            continue
        resolutions[rule.stable_id] = Resolution(CONFLICT, first.stable_id, "contradictory rules")
        findings.append(Finding("error", "contradictory_rules", (
            f"{rule.kind} {'.'.join(map(str, rule.key))}: {first.origin.ref} ({first.origin_layer}) and "
            f"{rule.origin.ref} ({rule.origin_layer}) disagree; the historical loader silently keeps the first"),
            rule.origin.ref, (first.stable_id, rule.stable_id)))


def _resolve_text(rules: list[Rule], resolutions: dict, findings: list) -> None:
    last: dict[tuple, Rule] = {}
    for rule in rules:
        key = (rule.kind, rule.key)
        previous = last.get(key)
        resolutions[rule.stable_id] = Resolution(EFFECTIVE)
        if previous is not None:
            if previous.legacy == rule.legacy:
                resolutions[previous.stable_id] = Resolution(DUPLICATE, rule.stable_id, "identical rule (later file wins)")
            else:
                resolutions[previous.stable_id] = Resolution(CONFLICT, rule.stable_id, "overridden by a later file")
                findings.append(Finding("error", "contradictory_text_rules", (
                    f"{rule.kind} {rule.payload.extension} {rule.payload.pattern!r}: {previous.origin.ref} is "
                    f"silently overridden by {rule.origin.ref}"), rule.origin.ref,
                    (previous.stable_id, rule.stable_id)))
        last[key] = rule


def _resolve_fields(step_rules: list[Rule], resolutions: dict, findings: list) -> None:
    """A renamed field is not removed (BaseMigrationScript.handle_fields),
    including on the new name of a model renamed by the same step."""
    renames = {
        r.key: r for r in step_rules
        if r.kind == RuleKind.RENAMED_FIELD and resolutions[r.stable_id].effective
        and not r.payload.is_blocker and legacy.IDENT_RE.fullmatch(r.payload.new_field or "")
    }
    new_models = {}
    for r in step_rules:
        if r.kind == RuleKind.RENAMED_MODEL and resolutions[r.stable_id].status in (EFFECTIVE, DUPLICATE):
            new_models.setdefault(r.payload.old_model, r.payload.new_model)
    for (model, name), rule in list(renames.items()):
        if model in new_models:
            renames.setdefault((new_models[model], name), rule)
    for r in step_rules:
        if r.kind == RuleKind.REMOVED_FIELD and resolutions[r.stable_id].effective and r.key in renames:
            resolutions[r.stable_id] = Resolution(SHADOWED_BY_RENAME, renames[r.key].stable_id,
                                                  "a renamed field is not removed")
    renamed_models = {r.payload.old_model: r for r in step_rules
                      if r.kind == RuleKind.RENAMED_MODEL and resolutions[r.stable_id].effective}
    for r in step_rules:
        if r.kind == RuleKind.REMOVED_MODEL and resolutions[r.stable_id].effective and r.payload.model in renamed_models:
            findings.append(Finding("warning", "removed_and_renamed_model", (
                f"{r.payload.model} is removed ({r.origin.ref}) and renamed ({renamed_models[r.payload.model].origin.ref}):"
                " the rename is applied first, the error only reports what is left"), r.origin.ref,
                (r.stable_id, renamed_models[r.payload.model].stable_id)))


def _signature(root: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".yaml", ".py"} and "__pycache__" not in path.parts:
            stat = path.stat()
            hasher.update(f"{path.relative_to(root).as_posix()}:{stat.st_size}:{stat.st_mtime_ns}\n".encode())
    return hasher.hexdigest()


def load_rules(root: pathlib.Path | None = None, *, python: bool = True) -> RuleSet:
    """Every rule (memoised on the recursive signature of the folder)."""
    root = pathlib.Path(root or loader.SCRIPTS_DIR)
    return _load_rules(_signature(root), str(root), python)


@functools.lru_cache(maxsize=4)
def _load_rules(signature: str, root_str: str, python: bool) -> RuleSet:
    root = pathlib.Path(root_str)
    # Python rules first: the YAML text rules override the script's own
    # dictionaries (BaseMigrationScript.parse_rules updates them)
    rules: list[Rule] = list(_python_rules()) if python and root == loader.SCRIPTS_DIR else []
    for category in legacy.LOAD_ORDER:
        for step in loader.step_names(category, root):
            for path in loader.rule_files(category, step, root):
                rules.extend(loader.load_file(path, category, root).rules)
    # unique stable ids (two files of a step may hold the same key)
    seen: dict[str, int] = defaultdict(int)
    unique = []
    for rule in rules:
        seen[rule.stable_id] += 1
        if seen[rule.stable_id] > 1:
            rule = dataclasses.replace(rule, stable_id=f"{rule.stable_id}#{seen[rule.stable_id]}")
        unique.append(rule)
    rules = unique

    resolutions: dict[str, Resolution] = {}
    findings: list[Finding] = []
    active_steps = set(loader.script_steps(root))
    orphans = sorted({r.step.name for r in rules if r.step.name not in active_steps})
    by_step: dict[str, list[Rule]] = defaultdict(list)
    for rule in rules:
        by_step[rule.step.name].append(rule)
    for step, step_rules in by_step.items():
        if step not in active_steps:
            for rule in step_rules:
                resolutions[rule.stable_id] = Resolution(INACTIVE, reason=f"no migration script loads {step}")
            continue
        for kind in RuleKind:
            same = [r for r in step_rules if r.kind == kind]
            if kind == RuleKind.PYTHON_TRANSFORM:
                for rule in same:
                    resolutions[rule.stable_id] = Resolution(EFFECTIVE)
            elif kind in TEXT_KINDS:
                _resolve_text(same, resolutions, findings)
            else:
                _resolve_list(same, resolutions, findings)
        _resolve_fields(step_rules, resolutions, findings)
    for step in orphans:
        files = sorted({r.origin.file.rsplit("/", 1)[0] for r in by_step[step]})
        findings.append(Finding("warning", "orphan_step", (
            f"no migrate_*.py loads {step}: its {len(by_step[step])} rule(s) are never applied"),
            ", ".join(files)))
    _cross_step(rules, resolutions, findings)
    return RuleSet(rules, resolutions, findings, orphans, signature)


def _cross_step(rules: list[Rule], resolutions: dict, findings: list) -> None:
    """A precise step and an allways step giving different answers."""
    always: dict[tuple, Rule] = {}
    for rule in rules:
        if rule.applies_always and resolutions[rule.stable_id].effective and rule.kind != RuleKind.PYTHON_TRANSFORM:
            always.setdefault((rule.kind, rule.key), rule)
    for rule in rules:
        if rule.applies_always or not resolutions[rule.stable_id].effective:
            continue
        other = always.get((rule.kind, rule.key))
        if other is not None and other.legacy != rule.legacy:
            findings.append(Finding("warning", "allways_overlap", (
                f"{rule.kind} {'.'.join(map(str, rule.key))}: {other.origin.ref} (allways) and {rule.origin.ref} "
                "differ; both scripts run on that interval"), rule.origin.ref, (other.stable_id, rule.stable_id)))


def _python_rules() -> list[Rule]:
    """Global functions of every script (class attribute and python_scripts),
    in the order BaseMigrationScript.run calls them."""
    import importlib
    import inspect

    from ..base_migration_script import BaseMigrationScript

    package = importlib.import_module("odoo_module_migrate.migration_scripts")
    result = []
    for step in loader.script_steps():
        module = importlib.import_module(f"{package.__name__}.{step}")
        classes = [c for _n, c in inspect.getmembers(module, inspect.isclass)
                   if c is not BaseMigrationScript and issubclass(c, BaseMigrationScript)
                   and c.__module__ == module.__name__]
        functions = [f for c in classes for f in getattr(c, "_GLOBAL_FUNCTIONS", [])]
        functions += loader.python_transform_functions(step)
        parsed = Step.parse(step)
        for cls in classes:
            result.extend(loader.python_text_rules(cls, parsed))
        result.extend(loader.python_rule(f, parsed) for f in functions)
    return result
