# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Canonical serialisation of a rule and the text indexed by the RAG."""

from __future__ import annotations

import dataclasses
import enum
import json
from typing import Any

from .models import Evidence, LegacyEvidence, Rule, RuleKind, TextRule


def _plain(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return value


def canonical(rule: Rule) -> dict[str, Any]:
    """JSON-able, key-sorted description of a rule (stable across runs: no
    line number in the identity, the origin is reported apart)."""
    return {
        "stable_id": rule.stable_id,
        "kind": rule.kind.value,
        "schema_version": rule.schema_version,
        "from_version": rule.from_version,
        "to_version": rule.to_version,
        "applies_always": rule.applies_always,
        "origin": {"file": rule.origin.file, "line": rule.origin.line, "layer": rule.origin.layer.value,
                   "fingerprint": rule.origin.fingerprint},
        "priority": rule.priority,
        "confidence": rule.confidence.value,
        "automation": rule.automation.value,
        "payload": _plain(rule.payload),
        "evidence": [dict(_plain(e), type=type(e).__name__) for e in rule.evidence],
        "preconditions": _plain(rule.preconditions),
        "postconditions": _plain(rule.postconditions),
        "legacy": rule.legacy,
        "note": rule.note,
    }


def dumps(rule: Rule) -> str:
    return json.dumps(canonical(rule), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _evidence_text(rule: Rule) -> list[str]:
    lines = []
    for item in rule.evidence:
        if isinstance(item, Evidence):
            lines.append(f"evidence: {item.text}")
        elif isinstance(item, LegacyEvidence) and item.location in ("comment", "group_comment", "inline_comment"):
            lines.extend(f"# {line}" for line in item.text.splitlines()[-3:])
    return lines


def summary_line(rule: Rule) -> str:
    """One line naming the symbols of the rule (old and new ones)."""
    p: Any = rule.payload
    kind = rule.kind
    if kind == RuleKind.DEPRECATED_MODULE:
        text = f"module {p.module} {p.change}" + (f" -> {p.target}" if p.target else "")
    elif kind == RuleKind.REMOVED_MODEL:
        text = f"model {p.model} {p.change}" + (f" -> {p.target_model}" if p.target_model else "")
        if p.target_module:
            text += f" (module {p.target_module})"
        if p.field_mapping:
            text += "; fields " + ", ".join(f"{a} -> {b}" for a, b in p.field_mapping)
    elif kind == RuleKind.RENAMED_MODEL:
        text = f"model {p.old_model} renamed -> {p.new_model}"
    elif kind == RuleKind.REMOVED_FIELD:
        text = f"field {p.model}.{p.field} {p.change}" + (f" -> {p.replacement}" if p.replacement else "")
    elif kind == RuleKind.RENAMED_FIELD:
        text = (f"field {p.model}.{p.old_field} NOT renamed (blocker)" if p.is_blocker
                else f"field {p.model}.{p.old_field} renamed -> {p.new_field}")
    elif kind == RuleKind.RENAMED_METHOD:
        text = f"method {p.model}.{p.old_method} renamed -> {p.new_method}"
    elif kind == RuleKind.FIELD_TYPE:
        text = f"field {p.model}.{p.field} type {p.old_type} -> {p.new_type}"
    elif kind == RuleKind.FIELD_PROPERTY:
        text = f"field {p.model}.{p.field} {p.property} {p.old_value} -> {p.new_value}"
    elif kind == RuleKind.MENU_PARENT_HINT:
        text = f"menu {p.surviving_child}: parent {p.removed_parent} removed, candidate {p.candidate_parent}"
    elif kind == RuleKind.MOVED_IMPORT:
        if p.reexport:
            text = f"import {p.from_module}.{p.name} -> {p.reexport}"
        elif p.to_module:
            text = f"import {p.from_module}.{p.name} moved -> from {p.to_module} import {p.name}"
        else:
            text = f"import {p.from_module}.{p.name} removed" + (f" (other definitions: {p.hint})" if p.hint else "")
    elif isinstance(p, TextRule):
        text = f"{p.extension} {p.pattern}: {p.value}"
    else:
        text = f"{p.module}.{p.function}"
    message = getattr(p, "message", None)
    if message and kind not in (RuleKind.TEXT_ERROR, RuleKind.TEXT_WARNING, RuleKind.TEXT_REPLACE):
        text += f" ({message})"
    return text


def rag_text(rule: Rule, source_line: str = "") -> str:
    """Body of the RAG chunk of a rule.

    A legacy rule keeps the text the RAG always indexed (up to three comments
    above, the extension section, the source line): its ranking does not move.
    A structured rule is rendered canonically, with its structured evidence.
    """
    if not rule.structured and source_line:
        comments = []
        for item in rule.evidence:
            if isinstance(item, LegacyEvidence) and item.location == "comment":
                comments = [f"# {c}" for c in item.text.splitlines()][-3:]
        section = f"{rule.payload.extension}: " if isinstance(rule.payload, TextRule) else ""
        return "\n".join([*comments, section + source_line.strip()])
    header = f"[{rule.kind} {rule.step.label}, {rule.origin.layer} {rule.confidence}, {rule.automation}]"
    lines = [header, summary_line(rule), *_evidence_text(rule)]
    if rule.note:
        lines.append(f"note: {rule.note}")
    return "\n".join(lines)
