# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Adapters between the rule entries of the YAML files and the typed rules.

Two entry formats are accepted in the same file:

* the historical one (a list, or ``{extension: {regex: value}}`` for the text
  rules), see :data:`CATEGORIES`;
* the structured v2 format: a mapping with ``schema_version: 2`` in place of
  the list (or of the text value).

``to_payload`` reads an entry, ``project`` returns its historical value: for a
legacy entry, the entry itself (unchanged); for a v2 entry, the list / value
that the historical format would have had, so that the migration scripts keep
consuming exactly the same data.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import (
    CONDITION_KINDS,
    Automation,
    ChangeKind,
    Condition,
    Confidence,
    DeprecatedModule,
    Evidence,
    FieldProperty,
    FieldType,
    LegacyEvidence,
    MenuParentHint,
    MovedImport,
    OriginLayer,
    Payload,
    RemovedField,
    RemovedModel,
    RenamedField,
    RenamedMethod,
    RenamedModel,
    Repository,
    RuleError,
    RuleKind,
    TextRule,
)

SCHEMA_VERSION = 2

MODEL_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")
IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")
MODULE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")  # Odoo has account_e-invoice_generate, *_273S_*
XMLID_RE = re.compile(r"^[a-z0-9_]+\.[A-Za-z0-9_.]+$")
EXTENSION_RE = re.compile(r"^(\*|\.[a-z0-9]+)$")

DEPRECATED_CHANGES = {ChangeKind.REMOVED, ChangeKind.RENAMED, ChangeKind.MERGED, ChangeKind.OCA_MOVED}


@dataclass(frozen=True)
class Category:
    folder: str  # folder of migration_scripts
    attribute: str  # BaseMigrationScript attribute
    container: str  # "list" or "text"
    kind: RuleKind | None  # None: text rules (kind given by the folder)
    arity: tuple[int, int] = (0, 0)  # (min, max) length of a legacy list entry


CATEGORIES = {
    c.folder: c for c in (
        Category("deprecated_modules", "_DEPRECATED_MODULES", "list", RuleKind.DEPRECATED_MODULE, (2, 4)),
        Category("removed_fields", "_REMOVED_FIELDS", "list", RuleKind.REMOVED_FIELD, (2, 3)),
        Category("removed_models", "_REMOVED_MODELS", "list", RuleKind.REMOVED_MODEL, (2, 2)),
        Category("renamed_fields", "_RENAMED_FIELDS", "list", RuleKind.RENAMED_FIELD, (3, 4)),
        Category("renamed_methods", "_RENAMED_METHODS", "list", RuleKind.RENAMED_METHOD, (3, 4)),
        Category("renamed_models", "_RENAMED_MODELS", "list", RuleKind.RENAMED_MODEL, (3, 3)),
        Category("field_types", "_FIELD_TYPES", "list", RuleKind.FIELD_TYPE, (5, 5)),
        Category("field_properties", "_FIELD_PROPERTIES", "list", RuleKind.FIELD_PROPERTY, (6, 6)),
        Category("menu_parent_hints", "_MENU_PARENT_HINTS", "list", RuleKind.MENU_PARENT_HINT, (4, 4)),
        # read by odoo_tools_imports.py (no script attribute), one mapping per rule
        Category("moved_imports", "", "list", RuleKind.MOVED_IMPORT),
        Category("text_replaces", "_TEXT_REPLACES", "text", RuleKind.TEXT_REPLACE),
        Category("text_errors", "_TEXT_ERRORS", "text", RuleKind.TEXT_ERROR),
        Category("text_warnings", "_TEXT_WARNINGS", "text", RuleKind.TEXT_WARNING),
    )
}
# Same order as BaseMigrationScript.parse_rules (dict order of its "rules")
LOAD_ORDER = (
    "field_types", "field_properties", "menu_parent_hints", "text_replaces", "text_errors",
    "text_warnings", "deprecated_modules", "removed_fields", "renamed_fields", "renamed_models",
    "renamed_methods", "removed_models", "moved_imports",
)
KIND_CATEGORY = {c.kind: c for c in CATEGORIES.values()}


def is_v2(entry: Any) -> bool:
    return isinstance(entry, dict) and "schema_version" in entry


# ------------------------------------------------------------------ legacy entries


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def legacy_payload(category: Category, entry: Any, where: str, extension: str = "", pattern: str = "") -> Payload:
    """Typed payload of a historical entry (no normalisation of its values)."""
    if category.container == "text":
        if not isinstance(pattern, str):
            raise RuleError(f"the pattern must be a string, not {type(pattern).__name__}", where)
        if not (isinstance(entry, str) or (entry is None and category.kind == RuleKind.TEXT_REPLACE)):
            raise RuleError(f"invalid value {entry!r} (a string is expected)", where)
        return TextRule(extension, pattern, entry)
    if category.kind == RuleKind.MOVED_IMPORT:
        return legacy_moved_import(entry, where)
    if not isinstance(entry, list):
        raise RuleError(f"a list or a schema_version 2 mapping is expected, not {type(entry).__name__}", where)
    low, high = category.arity
    if not low <= len(entry) <= high:
        raise RuleError(f"{len(entry)} element(s) where {low}..{high} are expected: {entry!r}", where)
    if not all(isinstance(v, str) or v is None for v in entry) or not entry[0]:
        raise RuleError(f"elements must be strings or null (the first one not empty): {entry!r}", where)
    kind = category.kind
    if kind == RuleKind.DEPRECATED_MODULE:
        change = ChangeKind.parse(entry[1], where)
        if change not in DEPRECATED_CHANGES:
            raise RuleError(f"invalid module change {entry[1]!r}", where)
        extra = [_text(v) for v in entry[2:]] + [None, None]
        return DeprecatedModule(entry[0], change, extra[0], extra[1])
    if kind == RuleKind.REMOVED_FIELD:
        return RemovedField(entry[0], str(entry[1]), *[_text(v) for v in entry[2:]])
    if kind == RuleKind.REMOVED_MODEL:
        return RemovedModel(entry[0], str(entry[1]))
    if kind == RuleKind.RENAMED_FIELD:
        return RenamedField(entry[0], str(entry[1]), _text(entry[2]), *[_text(v) for v in entry[3:]])
    if kind == RuleKind.RENAMED_METHOD:
        return RenamedMethod(entry[0], str(entry[1]), str(entry[2]), *[_text(v) for v in entry[3:]])
    if kind == RuleKind.RENAMED_MODEL:
        return RenamedModel(entry[0], str(entry[1]), str(entry[2] or ""))
    if kind == RuleKind.FIELD_TYPE:
        return FieldType(*[str(v) for v in entry])
    if kind == RuleKind.FIELD_PROPERTY:
        return FieldProperty(*[str(v) for v in entry])
    if kind == RuleKind.MENU_PARENT_HINT:
        return MenuParentHint(*[str(v) for v in entry])
    raise RuleError(f"unsupported rule kind {kind}", where)  # pragma: no cover


def legacy_evidence(payload: Payload) -> tuple[LegacyEvidence, ...]:
    """The source / message column of a historical entry, as legacy text."""
    for name in ("message", "value"):
        value = getattr(payload, name, None)
        if name == "value" and not isinstance(payload, TextRule):
            continue
        if isinstance(payload, TextRule) and payload.value is None:
            return ()
        if isinstance(value, str) and value.strip():
            return (LegacyEvidence(value.strip(), "value"),)
    return ()


def legacy_automation(kind: RuleKind, payload: Payload, layer: OriginLayer) -> Automation:
    """How the migrator uses the rule today (see BaseMigrationScript)."""
    if layer == OriginLayer.CANDIDATE:
        return Automation.MANUAL
    if kind == RuleKind.DEPRECATED_MODULE:
        assert isinstance(payload, DeprecatedModule)
        if payload.change == ChangeKind.REMOVED or not payload.target:
            return Automation.MANUAL  # error: replace the dependency by hand
        if payload.change == ChangeKind.OCA_MOVED:
            return Automation.DETERMINISTIC_WITH_VALIDATION  # "check it is available"
        return Automation.DETERMINISTIC  # depends rewritten
    if kind == RuleKind.RENAMED_FIELD:
        assert isinstance(payload, RenamedField)
        if payload.is_blocker:
            return Automation.BLOCKER
        if IDENT_RE.fullmatch(payload.new_field or ""):
            return Automation.DETERMINISTIC
        return Automation.RECOMMENDATION_ONLY  # "renamed to X: update it by hand"
    if kind == RuleKind.MOVED_IMPORT:
        # rewritten when the new module (or library) is known, else reported
        return Automation.DETERMINISTIC if (payload.to_module or payload.reexport) else Automation.MANUAL
    if kind in (RuleKind.RENAMED_MODEL, RuleKind.TEXT_REPLACE, RuleKind.PYTHON_TRANSFORM):
        return Automation.DETERMINISTIC
    if kind == RuleKind.REMOVED_FIELD:
        # displays removed from the views, every other usage reported
        return Automation.DETERMINISTIC_WITH_VALIDATION
    if kind in (RuleKind.REMOVED_MODEL, RuleKind.TEXT_ERROR):
        return Automation.MANUAL
    return Automation.RECOMMENDATION_ONLY  # warnings, methods, types, properties, menus


def legacy_confidence(kind: RuleKind, layer: OriginLayer) -> Confidence:
    if layer == OriginLayer.CANDIDATE:
        return Confidence.REJECTED_CANDIDATE
    if layer == OriginLayer.GENERATED:
        return Confidence.GENERATED
    if kind == RuleKind.TEXT_WARNING:
        return Confidence.HEURISTIC  # unverified rules are kept as warnings
    # Hand-written but without structured evidence: not "verified"
    return Confidence.UNKNOWN


# ------------------------------------------------------------------ v2 entries

COMMON_V2 = {"schema_version", "kind", "from_version", "to_version", "automation", "confidence",
             "evidence", "note", "validation", "preconditions", "postconditions"}

V2_FIELDS: dict[RuleKind, tuple[set[str], set[str]]] = {
    # kind: (required, optional)
    RuleKind.DEPRECATED_MODULE: ({"module", "change"}, {"target", "message"}),
    RuleKind.REMOVED_MODEL: ({"model", "message"},
                             {"change", "target_model", "target_module", "identity_preserved", "field_mapping"}),
    RuleKind.RENAMED_MODEL: ({"old_model", "new_model", "message"}, set()),
    RuleKind.REMOVED_FIELD: ({"model", "field"}, {"message", "change", "replacement"}),
    RuleKind.RENAMED_FIELD: ({"model", "old_field", "new_field"}, {"message"}),
    RuleKind.RENAMED_METHOD: ({"model", "old_method", "new_method"}, {"message"}),
    RuleKind.FIELD_TYPE: ({"model", "field", "old_type", "new_type", "message"}, set()),
    RuleKind.FIELD_PROPERTY: ({"model", "field", "property", "old_value", "new_value", "message"}, set()),
    RuleKind.MENU_PARENT_HINT: ({"removed_parent", "surviving_child", "candidate_parent", "message"}, set()),
    RuleKind.MOVED_IMPORT: ({"from_module", "name"}, {"to_module", "old_module", "reexport", "reexport_source",
                                                      "is_module", "deprecated", "hint", "message"}),
    RuleKind.TEXT_REPLACE: ({"replacement"}, set()),
    RuleKind.TEXT_ERROR: ({"message"}, set()),
    RuleKind.TEXT_WARNING: ({"message"}, set()),
}
EVIDENCE_FIELDS = {"repository", "commit", "title", "file", "lines", "url", "note"}
VALIDATION_FIELDS = {"target_model_required", "target_fields_required", "installation_required",
                     "tests_required", "target_module_required"}


def _str_field(entry, name, where, required=True, nullable=False):
    value = entry.get(name)
    if value is None:
        if required and not nullable and name in entry:
            raise RuleError(f"{name} may not be null", where)
        if required and name not in entry:
            raise RuleError(f"missing field {name!r}", where)
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise RuleError(f"{name} must be a string, not {type(value).__name__}", where)
    return str(value)


def v2_payload(kind: RuleKind, entry: dict, where: str, extension: str = "", pattern: str = "") -> Payload:
    required, optional = V2_FIELDS[kind]
    unknown = set(entry) - required - optional - COMMON_V2
    if unknown:
        raise RuleError(f"unknown field(s) {', '.join(sorted(map(str, unknown)))} for {kind}", where)
    missing = required - set(entry)
    if missing:
        raise RuleError(f"missing field(s) {', '.join(sorted(missing))} for {kind}", where)
    s = lambda name, **kw: _str_field(entry, name, where, **kw)
    if kind in (RuleKind.TEXT_REPLACE, RuleKind.TEXT_ERROR, RuleKind.TEXT_WARNING):
        name = "replacement" if kind == RuleKind.TEXT_REPLACE else "message"
        return TextRule(extension, pattern, s(name, nullable=kind == RuleKind.TEXT_REPLACE))
    if kind == RuleKind.DEPRECATED_MODULE:
        change = ChangeKind.parse(entry["change"], where)
        if change not in DEPRECATED_CHANGES:
            raise RuleError(f"invalid module change {change}", where)
        return DeprecatedModule(s("module"), change, s("target", required=False), s("message", required=False))
    if kind == RuleKind.REMOVED_MODEL:
        mapping = entry.get("field_mapping") or {}
        if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
            raise RuleError("field_mapping must be a {old_field: new_field} mapping of strings", where)
        preserved = entry.get("identity_preserved")
        if preserved is not None and not isinstance(preserved, bool):
            raise RuleError("identity_preserved must be true or false", where)
        return RemovedModel(
            s("model"), s("message"), ChangeKind.parse(entry.get("change", "removed"), where),
            s("target_model", required=False), s("target_module", required=False), preserved,
            tuple(mapping.items()),
        )
    if kind == RuleKind.RENAMED_MODEL:
        return RenamedModel(s("old_model"), s("new_model"), s("message"))
    if kind == RuleKind.REMOVED_FIELD:
        return RemovedField(s("model"), s("field"), s("message", required=False),
                            ChangeKind.parse(entry.get("change", "removed"), where), s("replacement", required=False))
    if kind == RuleKind.RENAMED_FIELD:
        return RenamedField(s("model"), s("old_field"), s("new_field", nullable=True), s("message", required=False))
    if kind == RuleKind.RENAMED_METHOD:
        return RenamedMethod(s("model"), s("old_method"), s("new_method"), s("message", required=False))
    if kind == RuleKind.FIELD_TYPE:
        return FieldType(s("model"), s("field"), s("old_type"), s("new_type"), s("message"))
    if kind == RuleKind.FIELD_PROPERTY:
        return FieldProperty(s("model"), s("field"), s("property"), s("old_value"), s("new_value"), s("message"))
    if kind == RuleKind.MOVED_IMPORT:
        flags = {}
        for name in ("is_module", "deprecated"):
            value = entry.get(name, False)
            if not isinstance(value, bool):
                raise RuleError(f"{name} must be true or false", where)
            flags[name] = value
        if entry.get("to_module") and entry.get("reexport"):
            raise RuleError("to_module and reexport exclude each other", where)
        return MovedImport(
            s("from_module"), s("name"), s("to_module", required=False), s("old_module", required=False),
            s("reexport", required=False), s("reexport_source", required=False), flags["is_module"],
            flags["deprecated"], s("hint", required=False), s("message", required=False),
        )
    if kind == RuleKind.MENU_PARENT_HINT:
        return MenuParentHint(s("removed_parent"), s("surviving_child"), s("candidate_parent"), s("message"))
    raise RuleError(f"unsupported rule kind {kind}", where)  # pragma: no cover


def v2_evidence(entry: dict, where: str) -> tuple[Evidence, ...]:
    raw = entry.get("evidence")
    if raw is None:
        return ()
    items = raw if isinstance(raw, list) else [raw]
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise RuleError("evidence must be a mapping (or a list of mappings)", where)
        unknown = set(item) - EVIDENCE_FIELDS
        if unknown:
            raise RuleError(f"unknown evidence field(s) {', '.join(sorted(map(str, unknown)))}", where)
        if "repository" not in item:
            raise RuleError("evidence.repository is required", where)
        values = {k: "" if item.get(k) is None else str(item[k]) for k in EVIDENCE_FIELDS - {"repository"}}
        result.append(Evidence(Repository.parse(item["repository"], where), **values))
    return tuple(result)


def v2_conditions(entry: dict, payload: Payload, where: str) -> tuple[tuple[Condition, ...], tuple[Condition, ...]]:
    """(preconditions, postconditions) from ``validation`` and the explicit lists."""
    pre, post = [], []
    validation = entry.get("validation") or {}
    if not isinstance(validation, dict):
        raise RuleError("validation must be a mapping", where)
    unknown = set(validation) - VALIDATION_FIELDS
    if unknown:
        raise RuleError(f"unknown validation field(s) {', '.join(sorted(map(str, unknown)))}", where)
    target_model = getattr(payload, "target_model", None) or getattr(payload, "new_model", None)
    if validation.get("target_model_required"):
        if not target_model:
            raise RuleError("target_model_required needs a target model", where)
        post.append(Condition("model_exists", (target_model,)))
    if validation.get("target_module_required"):
        module = getattr(payload, "target_module", None) or getattr(payload, "target", None)
        if not module:
            raise RuleError("target_module_required needs a target module", where)
        post.append(Condition("module_installable", (module,)))
    for field_name in validation.get("target_fields_required") or []:
        if not target_model:
            raise RuleError("target_fields_required needs a target model", where)
        post.append(Condition("field_exists", (target_model, str(field_name))))
    if validation.get("installation_required"):
        post.append(Condition("installation_required"))
    if validation.get("tests_required"):
        post.append(Condition("tests_required"))
    for name, bucket in (("preconditions", pre), ("postconditions", post)):
        for item in entry.get(name) or []:
            if not isinstance(item, dict) or set(item) - {"kind", "args"} or "kind" not in item:
                raise RuleError(f"{name} entries are {{kind, args}} mappings", where)
            if item["kind"] not in CONDITION_KINDS:
                raise RuleError(f"unknown condition kind {item['kind']!r}", where)
            bucket.append(Condition(item["kind"], tuple(str(a) for a in item.get("args") or ())))
    return tuple(pre), tuple(post)


# ------------------------------------------------------------------ projection


def _trim(values: list) -> list:
    while values and values[-1] is None:
        values.pop()
    return values


PROJECTIONS: dict[RuleKind, Callable[[Any], Any]] = {
    RuleKind.DEPRECATED_MODULE: lambda p: _trim([p.module, str(p.change), p.target, p.message]),
    RuleKind.REMOVED_MODEL: lambda p: [p.model, p.message],
    RuleKind.RENAMED_MODEL: lambda p: [p.old_model, p.new_model, p.message],
    RuleKind.REMOVED_FIELD: lambda p: _trim([p.model, p.field, p.message]),
    # the new name stays even when null: [model, field, null(, why)] is a blocker
    RuleKind.RENAMED_FIELD: lambda p: [p.model, p.old_field, p.new_field] + ([p.message] if p.message is not None else []),
    RuleKind.RENAMED_METHOD: lambda p: _trim([p.model, p.old_method, p.new_method, p.message]),
    RuleKind.FIELD_TYPE: lambda p: [p.model, p.field, p.old_type, p.new_type, p.message],
    RuleKind.FIELD_PROPERTY: lambda p: [p.model, p.field, p.property, p.old_value, p.new_value, p.message],
    RuleKind.MENU_PARENT_HINT: lambda p: [p.removed_parent, p.surviving_child, p.candidate_parent, p.message],
    RuleKind.MOVED_IMPORT: lambda p: project_moved_import(p),
    RuleKind.TEXT_REPLACE: lambda p: p.value,
    RuleKind.TEXT_ERROR: lambda p: p.value,
    RuleKind.TEXT_WARNING: lambda p: p.value,
}


def project(kind: RuleKind, payload: Payload) -> Any:
    """Historical value of a (v2) rule."""
    return PROJECTIONS[kind](payload)


# ------------------------------------------------------------------ moved imports
# Historical entry (tools/extract/extract_tools_exports.py): a mapping whose keys
# are present only when set: {from, name, to | import + source, old, module,
# deprecated, hint, proof}; "to" is always there except for a re-export.

_MOVED_IMPORT_KEYS = {"from", "name", "to", "old", "import", "source", "module", "deprecated", "hint", "proof"}


def legacy_moved_import(entry: Any, where: str) -> MovedImport:
    if not isinstance(entry, dict):
        raise RuleError(f"a mapping is expected, not {type(entry).__name__}", where)
    unknown = set(entry) - _MOVED_IMPORT_KEYS
    if unknown or not entry.get("from") or not entry.get("name"):
        raise RuleError(f"invalid moved import {entry!r}", where)
    return MovedImport(
        str(entry["from"]), str(entry["name"]), _text(entry.get("to")), _text(entry.get("old")),
        _text(entry.get("import")), _text(entry.get("source")), bool(entry.get("module")),
        bool(entry.get("deprecated")), _text(entry.get("hint")), _text(entry.get("proof")),
    )


def project_moved_import(p: MovedImport) -> dict:
    """The historical mapping, keys in the order of the extractor."""
    result: dict = {"from": p.from_module, "name": p.name}
    if p.reexport is not None:
        result["import"] = p.reexport
        if p.reexport_source is not None:
            result["source"] = p.reexport_source
    else:
        result["to"] = p.to_module
    for key, value in (("old", p.old_module), ("module", p.is_module or None),
                       ("deprecated", p.deprecated or None), ("hint", p.hint)):
        if value is not None:
            result[key] = value
    result["proof"] = p.message
    return result
