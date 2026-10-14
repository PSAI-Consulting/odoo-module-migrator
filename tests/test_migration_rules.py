# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Structured migration rules: formats, provenance, precedence, validation."""

import json
import os
import time

import pytest

from odoo_module_migrate import migration_rules
from odoo_module_migrate.migration_rules import loader, render
from odoo_module_migrate.migration_rules.models import (
    Automation,
    ChangeKind,
    Condition,
    Confidence,
    Evidence,
    LegacyEvidence,
    OriginLayer,
    Repository,
    RuleError,
    RuleKind,
    Step,
)
from odoo_module_migrate.migration_rules.ruleset import (
    BLOCKED,
    DUPLICATE,
    SHADOWED_BY_RENAME,
    SUPERSEDED,
)
from odoo_module_migrate.migration_rules.validation import SourceIndex, validate


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def scripts(tmp_path):
    root = tmp_path / "migration_scripts"
    for step in ("migrate_180_190", "migrate_190_200", "migrate_allways"):
        _write(root, f"{step}.py", "")
    return root


def _rules(root, python=False):
    return migration_rules.load_rules(root, python=python)


# ------------------------------------------------------------------ formats


LEGACY = {
    "deprecated_modules/migrate_190_200/curated.yaml": '- ["old_mod", "merged", "new_mod"]\n- ["gone", "removed"]\n',
    "removed_fields/migrate_190_200/generated.yaml": '- ["sale.order", "x_old", "odoo abc"]\n',
    "removed_models/migrate_190_200/generated.yaml": '- ["a.model", "odoo abc"]\n',
    "renamed_fields/migrate_190_200/generated.yaml": '- ["sale.order", "a", "b", "OpenUpgrade 20.0"]\n',
    "renamed_methods/migrate_190_200/curated.yaml": "- [sale.report, _a, _b, \"Odoo 20 sale_report.py\"]\n",
    "renamed_models/migrate_190_200/generated.yaml": '- ["old.model", "new.model", "odoo abc"]\n',
    "field_types/migrate_190_200/curated.yaml": '- ["sale.order.line", "f", "Float", "Integer", "src"]\n',
    "field_properties/migrate_190_200/curated.yaml": '- ["product.product", "p", "store", "False", "True", "src"]\n',
    "menu_parent_hints/migrate_180_190/curated.yaml": "- [a.b, a.c, a.d, \"src\"]\n",
    "text_errors/migrate_190_200/core_api.yaml": '.py:\n  "\\\\bfoo\\\\(": "[20] foo removed"\n',
    "text_warnings/migrate_190_200/x.yaml": '.py:\n  bar: "[20] check bar"\n',
    "text_replaces/migrate_190_200/x.yaml": '.xml:\n  "<tree": "<list"\n  "drop_me": null\n',
}


@pytest.mark.parametrize("rel,text", sorted(LEGACY.items()))
def test_every_legacy_format(scripts, rel, text):
    path = _write(scripts, rel, text)
    category = rel.split("/")[0]
    loaded = loader.load_file(path, category, scripts)
    assert loaded.rules
    import yaml

    assert loaded.document == yaml.safe_load(text)  # projection = historical data
    for rule in loaded.rules:
        assert rule.schema_version == 1 and rule.origin.file == rel and rule.origin.line >= 1


V2 = {
    RuleKind.DEPRECATED_MODULE: ("deprecated_modules", "module: m\n  change: renamed\n  target: n",
                                 ["m", "renamed", "n"]),
    RuleKind.REMOVED_MODEL: ("removed_models", ("model: hr.leave.type\n  change: merged\n  target_model: hr.work.entry.type\n"
                             "  target_module: hr_work_entry\n  identity_preserved: false\n"
                             "  field_mapping: {holiday_status_id: work_entry_type_id}\n  message: Merged"),
                             ["hr.leave.type", "Merged"]),
    RuleKind.RENAMED_MODEL: ("renamed_models", "old_model: a.b\n  new_model: a.c\n  message: src", ["a.b", "a.c", "src"]),
    RuleKind.REMOVED_FIELD: ("removed_fields", "model: a.b\n  field: f\n  message: m", ["a.b", "f", "m"]),
    RuleKind.RENAMED_FIELD: ("renamed_fields", "model: a.b\n  old_field: f\n  new_field: null\n  message: why",
                             ["a.b", "f", None, "why"]),
    RuleKind.RENAMED_METHOD: ("renamed_methods", "model: a.b\n  old_method: _f\n  new_method: _g", ["a.b", "_f", "_g"]),
    RuleKind.FIELD_TYPE: ("field_types", "model: a.b\n  field: f\n  old_type: Float\n  new_type: Integer\n  message: s",
                          ["a.b", "f", "Float", "Integer", "s"]),
    RuleKind.FIELD_PROPERTY: ("field_properties", ("model: a.b\n  field: f\n  property: store\n  old_value: 'False'\n"
                              "  new_value: 'True'\n  message: s"), ["a.b", "f", "store", "False", "True", "s"]),
    RuleKind.MENU_PARENT_HINT: ("menu_parent_hints", ("removed_parent: a.m\n  surviving_child: a.c\n"
                                "  candidate_parent: a.p\n  message: s"), ["a.m", "a.c", "a.p", "s"]),
}


@pytest.mark.parametrize("kind", sorted(V2, key=str))
def test_every_v2_kind_projects_to_legacy(scripts, kind):
    folder, body, expected = V2[kind]
    text = (f"- schema_version: 2\n  kind: {kind}\n  {body}\n  confidence: verified\n"
            "  evidence: {repository: odoo, commit: d37cf89a6ff, title: '[IMP] x'}\n")
    path = _write(scripts, f"{folder}/migrate_190_200/curated.yaml", text)
    (rule,) = loader.load_file(path, folder, scripts).rules
    assert rule.structured and rule.kind == kind and rule.legacy == expected
    assert rule.origin.line == 1 and rule.strong_proof
    assert rule.evidence[0] == Evidence(Repository.ODOO, commit="d37cf89a6ff", title="[IMP] x")


@pytest.mark.parametrize("kind,value,expected", [
    ("text_errors", ("{schema_version: 2, message: '[20] gone', confidence: verified, "
                    "evidence: {repository: odoo, commit: abc}}"), "[20] gone"),
    ("text_replaces", "{schema_version: 2, replacement: null}", None),
    ("text_warnings", "{schema_version: 2, message: check}", "check"),
])
def test_v2_text_rules(scripts, kind, value, expected):
    path = _write(scripts, f"{kind}/migrate_190_200/curated.yaml", f".py:\n  '\\bold\\b': {value}\n")
    loaded = loader.load_file(path, kind, scripts)
    assert loaded.document == {".py": {"\\bold\\b": expected}}
    assert loaded.rules[0].origin.line == 2


def test_mixed_legacy_and_v2_keep_the_order(scripts):
    path = _write(scripts, "renamed_fields/migrate_190_200/curated.yaml",
                  '- ["a.b", "f1", "g1", "src"]\n'
                  "- schema_version: 2\n  model: a.b\n  old_field: f2\n  new_field: g2\n"
                  '- ["a.b", "f3", null, "why"]\n')
    loaded = loader.load_file(path, "renamed_fields", scripts)
    assert loaded.document == [["a.b", "f1", "g1", "src"], ["a.b", "f2", "g2"], ["a.b", "f3", None, "why"]]
    assert [r.origin.line for r in loaded.rules] == [1, 2, 6]
    assert [r.automation for r in loaded.rules] == [Automation.DETERMINISTIC] * 2 + [Automation.BLOCKER]


# ------------------------------------------------------------------ provenance / identity


def test_stable_id_does_not_depend_on_lines(scripts):
    rel = "renamed_fields/migrate_190_200/generated.yaml"
    first = loader.load_file(_write(scripts, rel, '- ["a.b", "f", "g", "s"]\n'), "renamed_fields", scripts).rules[0]
    time.sleep(0.01)
    path = _write(scripts, rel, '# header\n\n- ["a.b", "x", "y", "s"]\n- ["a.b", "f", "g", "s"]\n')
    os.utime(path, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
    second = loader.load_file(path, "renamed_fields", scripts).rules[1]
    assert first.stable_id == second.stable_id == "renamed_field/migrate_190_200/a.b|f@generated"
    assert (first.origin.line, second.origin.line) == (1, 4)
    assert first.origin.fingerprint == second.origin.fingerprint


def test_comments_are_legacy_evidence_never_official(scripts):
    path = _write(scripts, "deprecated_modules/migrate_190_200/modules.yaml",
                  "# Generated by tools/extract_changes.py modules\n"
                  "- [\"old\", \"removed\"]  # odoo 1234567 '[REM] old'\n")
    rule = loader.load_file(path, "deprecated_modules", scripts).rules[0]
    assert rule.origin.layer == OriginLayer.GENERATED and rule.confidence == Confidence.GENERATED
    assert rule.evidence == (LegacyEvidence("odoo 1234567 '[REM] old'", "inline_comment"),)
    assert not rule.has_structured_evidence and not rule.strong_proof


def test_generated_header_makes_any_file_generated(scripts):
    path = _write(scripts, "text_errors/migrate_190_200/views.yaml",
                  "# Generated by tools/extract_changes.py views\n.xml:\n  x: y\n")
    assert loader.load_file(path, "text_errors", scripts).layer == OriginLayer.GENERATED


# ------------------------------------------------------------------ precedence


def test_curated_wins_blocks_and_renamed_field_is_not_removed(scripts):
    _write(scripts, "renamed_fields/migrate_190_200/curated.yaml",
           '- ["a.b", "blocked", null, "name swap"]\n- ["a.b", "same", "same", "column only"]\n'
           '- ["a.b", "fixed", "good", "verified"]\n')
    _write(scripts, "renamed_fields/migrate_190_200/generated.yaml",
           '- ["a.b", "blocked", "x", "s"]\n- ["a.b", "same", "y", "s"]\n- ["a.b", "fixed", "bad", "s"]\n'
           '- ["a.b", "moved", "new", "s"]\n')
    _write(scripts, "removed_fields/migrate_190_200/generated.yaml", '- ["a.b", "moved", "s"]\n- ["a.b", "blocked", "s"]\n')
    rules = _rules(scripts)
    status = {r.origin.ref: rules.resolutions[r.stable_id].status for r in rules.rules}
    assert status["renamed_fields/migrate_190_200/generated.yaml:1"] == BLOCKED
    assert status["renamed_fields/migrate_190_200/generated.yaml:2"] == BLOCKED
    assert status["renamed_fields/migrate_190_200/generated.yaml:3"] == SUPERSEDED
    assert status["removed_fields/migrate_190_200/generated.yaml:1"] == SHADOWED_BY_RENAME
    assert status["removed_fields/migrate_190_200/generated.yaml:2"] == "effective"  # blocker: still removed
    assert not rules.errors


def test_renamed_model_extends_field_renames(scripts):
    _write(scripts, "renamed_models/migrate_190_200/generated.yaml", '- ["old.m", "new.m", "s"]\n')
    _write(scripts, "renamed_fields/migrate_190_200/generated.yaml", '- ["old.m", "f", "g", "s"]\n')
    _write(scripts, "removed_fields/migrate_190_200/generated.yaml", '- ["new.m", "f", "s"]\n')
    rules = _rules(scripts)
    removed = next(r for r in rules.rules if r.kind == RuleKind.REMOVED_FIELD)
    assert rules.resolutions[removed.stable_id].status == SHADOWED_BY_RENAME


def test_structured_identity_preserving_model_successor_shadows_removal(scripts):
    _write(scripts, "renamed_models/migrate_190_200/generated.yaml", '- ["old.m", "new.m", "s"]\n')
    _write(
        scripts,
        "removed_models/migrate_190_200/curated.yaml",
        """- schema_version: 2
  kind: removed_model
  model: old.m
  change: renamed
  target_model: new.m
  identity_preserved: true
  confidence: unknown
  automation: recommendation_only
  message: reviewed successor
""",
    )
    rules = _rules(scripts)
    removed = next(r for r in rules.rules if r.kind == RuleKind.REMOVED_MODEL)
    assert rules.resolutions[removed.stable_id].status == SHADOWED_BY_RENAME
    assert not [f for f in rules.findings if f.code == "removed_and_renamed_model"]


def test_contradictions_are_errors_not_silent_choices(scripts):
    _write(scripts, "renamed_fields/migrate_190_200/curated.yaml", '- ["a.b", "f", "g", "s"]\n')
    _write(scripts, "renamed_fields/migrate_190_200/extra.yaml", '- ["a.b", "f", "h", "s"]\n')
    _write(scripts, "text_errors/migrate_190_200/a.yaml", ".py:\n  foo: one\n")
    _write(scripts, "text_errors/migrate_190_200/b.yaml", ".py:\n  foo: two\n")
    _write(scripts, "deprecated_modules/migrate_190_200/curated.yaml", '- ["m", "removed"]\n')
    _write(scripts, "deprecated_modules/migrate_190_200/modules.yaml", '- ["m", "renamed", "n"]\n')
    codes = sorted(f.code for f in _rules(scripts).errors)
    assert codes == ["contradictory_rules", "contradictory_text_rules", "removed_then_changed"]


def test_identical_duplicates_are_deduplicated(scripts):
    _write(scripts, "renamed_models/migrate_190_200/curated.yaml", '- ["a.b", "a.c", "s"]\n')
    _write(scripts, "renamed_models/migrate_190_200/generated.yaml", '- ["a.b", "a.c", "s"]\n')
    rules = _rules(scripts)
    ids = [r.stable_id for r in rules.rules]
    assert len(set(ids)) == 2
    assert rules.resolutions[ids[1]].status == DUPLICATE and not rules.errors


def test_allways_and_orphan_steps(scripts):
    _write(scripts, "renamed_methods/migrate_allways/curated.yaml", "- [a.b, _f, _g, s]\n")
    _write(scripts, "renamed_methods/migrate_190_200/curated.yaml", "- [a.b, _f, _h, s]\n")
    _write(scripts, "text_warnings/migrate_160_allways/x.yaml", ".py:\n  foo: bar\n")
    rules = _rules(scripts)
    always = next(r for r in rules.rules if r.step.name == "migrate_allways")
    assert always.applies_always and always.from_version is None and always.step.overlaps(170, 200)
    assert Step.parse("migrate_150_allways").to_code is None
    assert rules.orphan_steps == ["migrate_160_allways"]
    assert {f.code for f in rules.findings} >= {"allways_overlap", "orphan_step"}


# ------------------------------------------------------------------ candidates / errors


def test_commented_candidates_are_inactive_and_active_ones_refused(scripts):
    path = _write(scripts, "renamed_fields/migrate_190_200/candidates.yaml", '# - ["a.b", "f", "g", "s"]\n')
    assert loader.load_file(path, "renamed_fields", scripts).rules == ()
    assert migration_rules.legacy_documents("renamed_fields", "migrate_190_200", scripts) == []
    _write(scripts, "renamed_fields/migrate_190_200/candidates.yaml", '- ["a.b", "f", "g", "s"]\n')
    with pytest.raises(RuleError, match="candidates.yaml:1"):
        loader.load_file(path, "renamed_fields", scripts)


@pytest.mark.parametrize("rel,text,message", [
    ("text_errors/migrate_190_200/x.yaml", ".py:\n  ok: fine\n  '(unclosed': boom\n", r"x.yaml:3: invalid regex"),
    ("renamed_fields/migrate_190_200/curated.yaml", ("- schema_version: 2\n  model: a\n  old_field: b\n"
     "  new_field: c\n  colour: red\n"), r"curated.yaml:1: unknown field\(s\) colour"),
    ("deprecated_modules/migrate_190_200/curated.yaml", "- schema_version: 2\n  module: m\n  change: vanished\n",
     r"invalid ChangeKind 'vanished'"),
    ("removed_fields/migrate_190_200/curated.yaml", ("- schema_version: 2\n  model: a\n  field: b\n"
     "  automation: magic\n"), r"invalid Automation"),
    ("removed_fields/migrate_190_200/curated.yaml", ("- schema_version: 2\n  model: a\n  field: b\n"
     "  from_version: '18.0'\n"), r"from_version '18.0' does not match the folder migrate_190_200"),
    ("removed_fields/migrate_190_200/curated.yaml", "- schema_version: 2\n  kind: removed_model\n  model: a\n  field: b\n",
     r"does not match the folder"),
    ("removed_fields/migrate_190_200/generated.yaml", "- schema_version: 2\n  model: a\n  field: b\n",
     r"hand-written files"),
    ("removed_fields/migrate_190_200/curated.yaml", ("- schema_version: 2\n  model: a\n  field: b\n"
     "  confidence: verified\n"), r"verified rule needs a structured evidence"),
    ("removed_fields/migrate_190_200/curated.yaml", "- [only_one]\n", r"curated.yaml:1: 1 element"),
])
def test_invalid_rules_name_file_and_line(scripts, rel, text, message):
    path = _write(scripts, rel, text)
    with pytest.raises(RuleError, match=message):
        loader.load_file(path, rel.split("/")[0], scripts)
    assert any(f.level == "error" for f in validate(scripts, with_python=False).findings)


def test_invalid_step_folder():
    with pytest.raises(RuleError):
        Step.parse("migrate_200_190")


# ------------------------------------------------------------------ sources, validation


@pytest.mark.parametrize("comment,repository", [
    ("odoo 26cc6ac18fe '[IMP] base'", "odoo"), ("enterprise 3cd11e664cb", "enterprise"),
    ("OpenUpgrade 16.0 openupgrade_scripts/scripts/account/16.0.1.2/upgrade_analysis.txt", "openupgrade"),
    ("Commit https://github.com/OCA/commission/commit/49b0ff3", "oca"),
])
def test_sources_of_every_repository_stay_legacy_text(scripts, comment, repository):
    path = _write(scripts, "removed_models/migrate_190_200/generated.yaml", f'- ["a.b", "{comment}"]\n')
    rule = loader.load_file(path, "removed_models", scripts).rules[0]
    assert rule.evidence == (LegacyEvidence(comment, "value"),)
    v2 = _write(scripts, "removed_models/migrate_190_200/curated.yaml",
                f"- schema_version: 2\n  model: c.d\n  message: m\n  evidence: {{repository: {repository}, commit: x}}\n")
    assert loader.load_file(v2, "removed_models", scripts).rules[0].evidence[0].repository == repository


def test_validator_checks_targets_against_sources(scripts, tmp_path):
    _write(scripts, "renamed_models/migrate_190_200/generated.yaml", '- ["a.b", "a.missing", "s"]\n')
    addons = tmp_path / "addons"
    _write(addons, "base/__manifest__.py", "{}")
    _write(addons, "base/models/x.py", "class X:\n    _name = 'a.present'\n    name = fields.Char()\n")
    index = SourceIndex.build([addons])
    assert index.models == {"a.present"} and "name" in index.fields and "base" in index.modules
    report = validate(scripts, odoo_sources=[addons], with_python=False)
    assert [f.code for f in report.findings if f.code == "missing_target"] == ["missing_target"]


def test_conditions_api():
    class Facts:
        def has_model(self, name):
            return name == "hr.work.entry.type"

    assert Condition("model_exists", ("hr.work.entry.type",)).evaluate(Facts()) is True
    assert Condition("model_exists", ("x.y",)).evaluate(Facts()) is False
    assert Condition("field_exists", ("a", "b")).evaluate(Facts()) is None  # unknown, never True


def test_canonical_serialisation_is_stable(scripts):
    path = _write(scripts, "removed_models/migrate_190_200/curated.yaml",
                  "- schema_version: 2\n  model: hr.leave.type\n  change: merged\n  target_model: hr.work.entry.type\n"
                  "  message: Merged\n  field_mapping: {b: c, a: d}\n")
    rule = loader.load_file(path, "removed_models", scripts).rules[0]
    first = render.dumps(rule)
    assert first == render.dumps(rule) and json.loads(first)["payload"]["change"] == "merged"
    assert "hr.work.entry.type" in render.rag_text(rule) and "a -> d" in render.rag_text(rule)
    assert rule.payload.change == ChangeKind.MERGED


def test_cache_invalidated_by_nested_change(scripts):
    rel = "renamed_fields/migrate_190_200/curated.yaml"
    path = _write(scripts, rel, '- ["a.b", "f", "g", "s"]\n')
    assert _rules(scripts).rules[0].payload.new_field == "g"
    path.write_text('- ["a.b", "f", "h", "s"]\n', encoding="utf-8")
    os.utime(path, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
    assert _rules(scripts).rules[0].payload.new_field == "h"


def test_files_are_loaded_in_sorted_order(scripts):
    for name in ("b.yaml", "A.yaml", "a_b.yaml", "curated.yaml", "generated.yaml"):
        _write(scripts, f"text_errors/migrate_190_200/{name}", ".py:\n  x: y\n")
    names = [p.name for p in loader.rule_files("text_errors", "migrate_190_200", scripts)]
    assert names == sorted(names)
    assert names.index("curated.yaml") < names.index("generated.yaml")


def test_python_transform_functions_are_registered_sorted():
    functions = migration_rules.python_transform_functions("migrate_190_200")
    files = [f.__module__.rsplit(".", 1)[-1] for f in functions]
    assert files == sorted(files) and "migrate_toggle_active_buttons" in [f.__name__ for f in functions]
    rules = migration_rules.load_rules()
    toggle = next(r for r in rules.rules if r.kind == RuleKind.PYTHON_TRANSFORM
                  and r.payload.function == "migrate_toggle_active_buttons")
    assert toggle.origin.file == "python_scripts/migrate_190_200/toggle_active.py" and toggle.origin.line > 1


def test_repository_rules_load_without_error():
    report = validate()
    assert not report.errors, [str(f) for f in report.errors]
    assert not report.ruleset.errors
    # every hand-written rule but the three undocumented text replaces has a justification
    assert sum(f.code == "unjustified_curated" for f in report.findings) <= 3
