# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Structured migration rules (see docs/migration_rules.md).

* :mod:`.models` typed immutable rules, payloads and enums;
* :mod:`.legacy` historical / v2 entry adapters and the legacy projection;
* :mod:`.loader` the one reader of the rule files (lines, layers, cache);
* :mod:`.ruleset` precedence and conflicts;
* :mod:`.validation` checks and per-step summary (``python -m odoo_module_migrate.migration_rules``);
* :mod:`.render` canonical serialisation and the text indexed by the RAG.

The helpers below replace the direct YAML reads of the other modules.
"""

from __future__ import annotations

import re

from .legacy import CATEGORIES, LOAD_ORDER
from .loader import (
    SCRIPTS_DIR,
    legacy_documents,
    load_file,
    python_transform_functions,
    rule_files,
    step_rules,
)
from .models import (
    Automation,
    ChangeKind,
    Condition,
    Confidence,
    Evidence,
    LegacyEvidence,
    OriginLayer,
    Rule,
    RuleError,
    RuleKind,
    Step,
)
from .ruleset import RuleSet, load_rules

__all__ = [
    "CATEGORIES",
    "LOAD_ORDER",
    "SCRIPTS_DIR",
    "Automation",
    "ChangeKind",
    "Condition",
    "Confidence",
    "Evidence",
    "LegacyEvidence",
    "OriginLayer",
    "Rule",
    "RuleError",
    "RuleKind",
    "RuleSet",
    "Step",
    "curated_keys",
    "legacy_documents",
    "load_file",
    "load_rules",
    "merged_module_rules",
    "module_aliases",
    "python_transform_functions",
    "rule_files",
    "step_rules",
]


def _step_folder(start: int, end: int) -> str:
    return f"migrate_{start * 10:03d}_{end * 10:03d}"


def _module_rows(step: str) -> list:
    return [row for _path, document in legacy_documents("deprecated_modules", step) for row in document]


def module_aliases(from_version: str, to_version: str) -> dict[str, str]:
    """{old module: new module} merged / renamed between two versions (the
    first rule of the first step wins), for upgrade_code."""
    aliases: dict[str, str] = {}
    for major in range(int(float(from_version)), int(float(to_version))):
        for row in _module_rows(_step_folder(major, major + 1)):
            if len(row) > 2 and row[1] in {"merged", "renamed"} and row[2]:
                aliases.setdefault(row[0], row[2])
    return aliases


def merged_module_rules(target_code: int) -> list:
    """Merged module rows of every step up to ``target_code`` (step order)."""
    rows = []
    base = SCRIPTS_DIR / "deprecated_modules"
    for step in sorted(p.name for p in base.glob("migrate_*_*")):
        match = re.fullmatch(r"migrate_(\d+)_(\d+)", step)
        if not match or int(match.group(2)) > target_code:
            continue
        rows.extend(row for row in _module_rows(step) if len(row) > 2 and row[1] == "merged")
    return rows


def curated_keys(path) -> set[str]:
    """First column of the rules of a hand-written file (legacy or v2): the
    extractors skip these keys when they regenerate the generated files."""
    import pathlib

    path = pathlib.Path(path)
    if not path.exists():
        return set()
    category = path.parent.parent.name
    if category not in CATEGORIES:
        raise RuleError(f"{path} is not in a rule category folder")
    return {rule.key[0] for rule in load_file(path, category, path.parent.parent.parent).rules}
