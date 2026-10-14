# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Typed, immutable migration rules.

A :class:`Rule` is one entry of a rule file of ``migration_scripts`` (or one
public function of a Python transformation), with its exact origin (file,
line, layer), its evidence, its confidence and how the migrator uses it
(:class:`Automation`). The data specific to each kind is a distinct payload
class, never a catch-all structure of optional fields.

The historical value of the entry (what ``yaml.safe_load`` returned for it)
is kept in :attr:`Rule.legacy`: :mod:`.legacy` projects every rule, legacy or
structured (v2), to this exact historical form, which the migration scripts
still consume.
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


class _Enum(str, enum.Enum):
    def __str__(self) -> str:
        return self.value

    @classmethod
    def parse(cls, value: Any, where: str = ""):
        try:
            return cls(value)
        except ValueError:
            allowed = ", ".join(m.value for m in cls)
            raise RuleError(f"invalid {cls.__name__} {value!r} (allowed: {allowed})", where) from None


class RuleKind(_Enum):
    DEPRECATED_MODULE = "deprecated_module"
    REMOVED_MODEL = "removed_model"
    RENAMED_MODEL = "renamed_model"
    REMOVED_FIELD = "removed_field"
    RENAMED_FIELD = "renamed_field"
    RENAMED_METHOD = "renamed_method"
    FIELD_TYPE = "field_type"
    FIELD_PROPERTY = "field_property"
    MENU_PARENT_HINT = "menu_parent_hint"
    TEXT_REPLACE = "text_replace"
    TEXT_ERROR = "text_error"
    TEXT_WARNING = "text_warning"
    PYTHON_TRANSFORM = "python_transform"
    MOVED_IMPORT = "moved_import"


class OriginLayer(_Enum):
    CURATED = "curated"
    GENERATED = "generated"
    CANDIDATE = "candidate"
    PYTHON = "python"


class Confidence(_Enum):
    VERIFIED = "verified"
    GENERATED = "generated"
    HEURISTIC = "heuristic"
    REJECTED_CANDIDATE = "rejected_candidate"
    UNKNOWN = "unknown"


class Automation(_Enum):
    DETERMINISTIC = "deterministic"
    DETERMINISTIC_WITH_VALIDATION = "deterministic_with_validation"
    RECOMMENDATION_ONLY = "recommendation_only"
    MANUAL = "manual"
    BLOCKER = "blocker"


class ChangeKind(_Enum):
    REMOVED = "removed"
    RENAMED = "renamed"
    MOVED = "moved"
    RENAMED_AND_MOVED = "renamed_and_moved"
    MERGED = "merged"
    SPLIT = "split"
    REPLACED = "replaced"
    PARTIALLY_REPLACED = "partially_replaced"
    OCA_MOVED = "oca_moved"
    BEHAVIOR_CHANGED = "behavior_changed"
    UNKNOWN = "unknown"


class Repository(_Enum):
    ODOO = "odoo"
    ENTERPRISE = "enterprise"
    OPENUPGRADE = "openupgrade"
    OCA = "oca"
    MIGRATOR = "migrator"


# Priority of the layers when two rules share a semantic key (lower wins).
# The historical "first rule wins" order of the files is kept inside a layer.
PRIORITY_CURATED_STRUCTURED = 1
PRIORITY_CURATED_LEGACY = 2
PRIORITY_GENERATED = 3
PRIORITY_HEURISTIC = 4
PRIORITY_CANDIDATE = 5


class RuleError(ValueError):
    """Invalid rule: the message always names the file and the line."""

    def __init__(self, message: str, where: str = ""):
        self.where = where
        super().__init__(f"{where}: {message}" if where else message)


# ------------------------------------------------------------------ steps


@dataclass(frozen=True, order=True)
class Step:
    """Version interval of a rule folder (``migrate_190_200``,
    ``migrate_150_allways``, ``migrate_allways``)."""

    name: str
    from_code: int | None  # 190 for 19.0; None for migrate_allways
    to_code: int | None  # None: up to the latest version (allways)

    @property
    def applies_always(self) -> bool:
        return self.to_code is None

    @property
    def from_version(self) -> str | None:
        return None if self.from_code is None else f"{self.from_code // 10}.0"

    @property
    def to_version(self) -> str | None:
        return None if self.to_code is None else f"{self.to_code // 10}.0"

    @property
    def label(self) -> str:
        start = self.from_version or "*"
        end = self.to_version or "*"
        return f"{start} -> {end}" + (" (allways)" if self.applies_always else "")

    @classmethod
    def parse(cls, name: str) -> Step:
        parts = name.split("_")
        if len(parts) == 2 and parts == ["migrate", "allways"]:
            return cls(name, None, None)
        if len(parts) != 3 or parts[0] != "migrate" or not parts[1].isdigit():
            raise RuleError(f"invalid step folder {name!r} (migrate_XXX_YYY or migrate_XXX_allways)")
        start = int(parts[1])
        if parts[2] == "allways":
            return cls(name, start, None)
        if not parts[2].isdigit() or int(parts[2]) <= start:
            raise RuleError(f"invalid step folder {name!r}: the target must follow the start")
        return cls(name, start, int(parts[2]))

    def overlaps(self, init_code: int, target_code: int) -> bool:
        """Same selection as ``Migration._get_migration_scripts``."""
        start = self.from_code if self.from_code is not None else 0
        end = self.to_code if self.to_code is not None else 10**6
        return not (start >= target_code or end <= init_code)


# ------------------------------------------------------------------ origin / evidence


@dataclass(frozen=True)
class Origin:
    file: str  # path relative to migration_scripts, POSIX separators
    line: int  # 1-based line of the entry
    layer: OriginLayer
    fingerprint: str  # sha256 (16 hex) of the canonical content

    @property
    def ref(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(frozen=True)
class LegacyEvidence:
    """Free text of a historical rule (its source column or the comments that
    precede / follow it). Never promoted to an official evidence: it was not
    parsed with certainty."""

    text: str
    location: str = "value"  # value | comment | group_comment | inline_comment | docstring

    @property
    def structured(self) -> bool:
        return False


@dataclass(frozen=True)
class Evidence:
    """Structured functional evidence of a v2 rule."""

    repository: Repository
    commit: str = ""
    title: str = ""
    file: str = ""
    lines: str = ""
    url: str = ""
    note: str = ""

    @property
    def structured(self) -> bool:
        return True

    @property
    def text(self) -> str:
        parts = [str(self.repository)]
        if self.commit:
            parts.append(self.commit)
        if self.title:
            parts.append(repr(self.title))
        if self.file:
            parts.append(self.file + (f":{self.lines}" if self.lines else ""))
        if self.note:
            parts.append(f"({self.note})")
        return " ".join(parts)


AnyEvidence = Evidence | LegacyEvidence


@dataclass(frozen=True)
class Condition:
    """Pre/postcondition that a future applicator (Lot B) must establish.

    ``kind``: model_exists, field_exists, module_installable,
    installation_required, tests_required.
    """

    kind: str
    args: tuple[str, ...] = ()

    def evaluate(self, facts: Any) -> bool | None:
        """True / False when ``facts`` can tell, None when unknown.

        ``facts`` may provide ``has_model(name)``, ``has_field(model, field)``
        and ``has_module(name)``; anything missing gives None (never True).
        """
        probe = {
            "model_exists": "has_model",
            "field_exists": "has_field",
            "module_installable": "has_module",
        }.get(self.kind)
        method = getattr(facts, probe, None) if probe else None
        if method is None:
            return None
        result = method(*self.args)
        return None if result is None else bool(result)


CONDITION_KINDS = {"model_exists", "field_exists", "module_installable", "installation_required", "tests_required"}


# ------------------------------------------------------------------ payloads


@dataclass(frozen=True)
class DeprecatedModule:
    module: str
    change: ChangeKind  # removed | renamed | merged | oca_moved
    target: str | None = None
    message: str | None = None

    def key(self):
        return (self.module,)


@dataclass(frozen=True)
class RemovedModel:
    model: str
    message: str
    change: ChangeKind = ChangeKind.REMOVED
    target_model: str | None = None
    target_module: str | None = None
    identity_preserved: bool | None = None
    field_mapping: tuple[tuple[str, str], ...] = ()

    def key(self):
        return (self.model,)


@dataclass(frozen=True)
class RenamedModel:
    old_model: str
    new_model: str
    message: str = ""

    def key(self):
        return (self.old_model,)


@dataclass(frozen=True)
class RemovedField:
    model: str
    field: str
    message: str | None = None
    change: ChangeKind = ChangeKind.REMOVED
    replacement: str | None = None

    def key(self):
        return (self.model, self.field)


@dataclass(frozen=True)
class RenamedField:
    model: str
    old_field: str
    new_field: str | None  # None: explicitly NOT renamed (blocker)
    message: str | None = None

    def key(self):
        return (self.model, self.old_field)

    @property
    def is_blocker(self) -> bool:
        return self.new_field is None or self.new_field == self.old_field


@dataclass(frozen=True)
class RenamedMethod:
    model: str
    old_method: str
    new_method: str
    message: str | None = None

    def key(self):
        return (self.model, self.old_method)


@dataclass(frozen=True)
class FieldType:
    model: str
    field: str
    old_type: str
    new_type: str
    message: str

    def key(self):
        return (self.model, self.field)


@dataclass(frozen=True)
class FieldProperty:
    model: str
    field: str
    property: str
    old_value: str
    new_value: str
    message: str

    def key(self):
        return (self.model, self.field, self.property)


@dataclass(frozen=True)
class MenuParentHint:
    removed_parent: str
    surviving_child: str
    candidate_parent: str
    message: str = ""

    def key(self):
        return (self.removed_parent, self.surviving_child)


@dataclass(frozen=True)
class TextRule:
    """text_replace (value = replacement or None: remove the match),
    text_error / text_warning (value = message)."""

    extension: str
    pattern: str
    value: str | None

    def key(self):
        return (self.extension, self.pattern)


@dataclass(frozen=True)
class MovedImport:
    """``from <from_module> import <name>`` does not work anymore.

    to_module: where to import it from (None: removed); reexport: the import
    statement of the library it was re-exported from; is_module: the name is
    a module; old_module: where it was defined; hint: other definitions of
    the same name (different code)."""

    from_module: str
    name: str
    to_module: str | None = None
    old_module: str | None = None
    reexport: str | None = None
    reexport_source: str | None = None
    is_module: bool = False
    deprecated: bool = False
    hint: str | None = None
    message: str | None = None  # the "proof" of the extracted rule

    def key(self):
        return (self.from_module, self.name)


@dataclass(frozen=True)
class PythonTransform:
    module: str  # dotted module of the function
    function: str
    description: str = ""
    upgrade_code: bool = False  # behaviour depends on the upgrade_code run

    def key(self):
        return (self.module, self.function)


Payload = (
    DeprecatedModule | RemovedModel | RenamedModel | RemovedField | RenamedField | RenamedMethod |
    FieldType | FieldProperty | MenuParentHint | TextRule | PythonTransform | MovedImport
)


# ------------------------------------------------------------------ rule


@dataclass(frozen=True)
class Rule:
    stable_id: str
    kind: RuleKind
    step: Step
    origin: Origin
    priority: int
    payload: Payload
    confidence: Confidence
    automation: Automation
    evidence: tuple[AnyEvidence, ...] = ()
    preconditions: tuple[Condition, ...] = ()
    postconditions: tuple[Condition, ...] = ()
    schema_version: int = 1
    legacy: Any = None  # exact historical value (what the scripts consume)
    note: str = ""

    # ---- convenience
    @property
    def from_version(self) -> str | None:
        return self.step.from_version

    @property
    def to_version(self) -> str | None:
        return self.step.to_version

    @property
    def applies_always(self) -> bool:
        return self.step.applies_always

    @property
    def origin_file(self) -> str:
        return self.origin.file

    @property
    def origin_line(self) -> int:
        return self.origin.line

    @property
    def origin_layer(self) -> OriginLayer:
        return self.origin.layer

    @property
    def structured(self) -> bool:
        return self.schema_version >= 2

    @property
    def key(self) -> tuple:
        return self.payload.key()

    @property
    def has_structured_evidence(self) -> bool:
        return any(e.structured for e in self.evidence)

    @property
    def strong_proof(self) -> bool:
        """Only a structured, verified curated rule with structured evidence
        is a strong proof; a legacy rule keeps a lower level."""
        return (
            self.structured
            and self.origin.layer == OriginLayer.CURATED
            and self.confidence == Confidence.VERIFIED
            and self.has_structured_evidence
        )


def content_fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class Finding:
    """Validation finding: ``level`` is error or warning."""

    level: str
    code: str
    message: str
    where: str = ""
    rules: tuple[str, ...] = field(default_factory=tuple)

    def __str__(self) -> str:
        return f"{self.level.upper()} [{self.code}] {self.where + ': ' if self.where else ''}{self.message}"
