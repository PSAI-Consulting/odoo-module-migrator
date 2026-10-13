# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""The structured rule layer changes nothing in the deterministic migration.

* ``tests/fixtures/rules_baseline.json`` was captured with the historical
  loader (commit 19a5551, before migration_rules existed): every script, every
  attribute, every per-extension text rule and the rules read outside the
  scripts (upgrade_code aliases, merged modules, odoo.tools error patterns)
  must still have the same digest, order and priority included;
* every legacy rule file still gives exactly what ``yaml.safe_load`` gives;
* the RAG never offers more proofs than before (no new automatic edit).
"""

import pathlib
import sys

import pytest
import yaml

from odoo_module_migrate import migration_rules
from odoo_module_migrate.intelligence import confidence, rag
from odoo_module_migrate.migration_rules import legacy, loader
from odoo_module_migrate.migration_rules.models import Automation, OriginLayer, RuleKind

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import rules_baseline

SCRIPTS = loader.SCRIPTS_DIR
RULE_FILES = sorted(p for c in legacy.CATEGORIES for p in (SCRIPTS / c).glob("*/*.yaml"))


@pytest.fixture(scope="module")
def snapshot():
    return rules_baseline.summary(rules_baseline.snapshot())


def test_every_step_matches_the_historical_baseline(snapshot):
    expected = rules_baseline.json.loads(rules_baseline.FIXTURE.read_text(encoding="utf-8"))
    assert rules_baseline.differences(expected, snapshot) == []


def test_baseline_covers_every_script_and_reader(snapshot):
    scripts = {p.stem for p in SCRIPTS.glob("migrate_*.py")}
    assert scripts <= set(snapshot)
    readers = snapshot["<readers>"]
    assert sum(k.startswith("upgrade_code_aliases:") for k in readers) == 78  # every (start, end) pair from 8.0 to 20.0
    assert any(k.startswith("tools_import_error_patterns:") for k in readers)


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda p: p.relative_to(SCRIPTS).as_posix())
def test_legacy_files_give_the_historical_data(path):
    """For a file without v2 entry, the loader returns exactly what the
    historical ``yaml.safe_load`` returned (projection = identity)."""
    category = path.relative_to(SCRIPTS).parts[0]
    loaded = loader.load_file(path, category)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if any(rule.structured for rule in loaded.rules):
        # v2 pilot: same projection as the historical entry it replaced
        # (proved by the baseline digests above)
        assert loaded.document is not None
        return
    assert loaded.document == raw


def test_generated_files_are_never_structured():
    rules = migration_rules.load_rules(python=False)
    assert not [r.origin.ref for r in rules.rules if r.origin_layer == OriginLayer.GENERATED and r.structured]


def test_curated_keys_of_the_extractor_are_unchanged():
    """extract_changes.py modules skips the same curated modules as before."""
    for path in sorted((SCRIPTS / "deprecated_modules").glob("*/curated.yaml")):
        historical = {item[0] for item in yaml.safe_load(path.read_text(encoding="utf-8")) or []
                      if isinstance(item, list)}
        historical |= {item["module"] for item in yaml.safe_load(path.read_text(encoding="utf-8")) or []
                       if isinstance(item, dict)}
        assert migration_rules.curated_keys(path) == historical, path


# ------------------------------------------------------------------ RAG / auto-application


def test_rag_proofs_are_only_effective_rules():
    rules = migration_rules.load_rules(python=False)
    by_ref = {f"migration_scripts/{r.origin.ref}": r for r in rules.rules}
    for item in rag.rule_corpus():
        if item["type"] not in rag.PROOF_TYPES or "rule" not in item:
            continue
        rule = by_ref[f"{item['rel_path']}:{item['line']}"]
        assert rules.effective(rule), rule.origin.ref
        assert rule.automation != Automation.BLOCKER
        assert rule.origin_layer in (OriginLayer.CURATED, OriginLayer.GENERATED)
        assert (item["type"] == "rule_generated") == (rule.origin_layer == OriginLayer.GENERATED)


def test_no_new_automatic_edit_is_opened():
    """Weights of the proofs unchanged; candidates, blocked / superseded rules
    and blockers are never proofs; the proof set only shrank."""
    assert confidence.PROOF_WEIGHTS == {"rule_curated": 0.25, "upgrade_code": 0.25, "rule_generated": 0.20}
    assert rag.PROOF_TYPES == {"rule_curated", "rule_generated", "upgrade_code"}
    corpus = rag.rule_corpus()
    assert not any("candidates" in i["rel_path"] for i in corpus)
    blockers = [i for i in corpus if i["type"] == "rule_blocker"]
    assert blockers and all(not i["rule"].get("rename") for i in blockers)
    rules = migration_rules.load_rules(python=False)
    blocked = {f"migration_scripts/{r.origin.ref}" for r in rules.rules if not rules.effective(r)}
    assert not {f"{i['rel_path']}:{i['line']}" for i in corpus} & blocked


def test_blocked_generated_rename_is_not_a_proof():
    """renamed_fields/migrate_110_120: curated null blocks the generated
    sale.order.requested_date -> commitment_date."""
    corpus = rag.rule_corpus()
    renames = [i["rule"].get("rename") for i in corpus if i.get("rule", {}).get("kind") == "renamed_field"]
    assert ("requested_date", "commitment_date") not in renames
    assert any(i["type"] == "rule_blocker" and "requested_date" in i["body"] for i in corpus)


def test_rag_retrieves_the_structured_rule():
    from odoo_module_migrate import report

    module = ROOT / "tests"  # any directory: no module source needed here
    rep = report.ModuleReport("x", module)
    entry = report.Entry("ERROR", "The model hr.leave.type has been deprecated", "models/x.py", 1)
    engine = rag.HybridRAG(rep, "19.0", "20.0")
    chunks = engine.retrieve_rules([entry], None, 6000)
    structured = [c for c in chunks if c.rule.get("structured")]
    assert structured and structured[0].rule["kind"] == "removed_model"
    assert "hr.work.entry.type" in structured[0].content and structured[0].proof_strength == "strong"
    assert 'rule="removed_model/migrate_190_200/hr.leave.type@curated"' in structured[0].render_tagged("t")


def test_generated_text_rules_are_labelled_generated():
    """views.yaml / js_modules.yaml are extracted ("Generated by" header):
    they were indexed as hand-written proofs before."""
    corpus = rag.rule_corpus()
    views = [i for i in corpus if i["rel_path"].endswith("text_errors/migrate_190_200/views.yaml")]
    assert views and {i["type"] for i in views} == {"rule_generated"}


def test_python_transforms_are_all_inventoried():
    rules = migration_rules.load_rules()
    transforms = [r for r in rules.rules if r.kind == RuleKind.PYTHON_TRANSFORM]
    snapshot = rules_baseline.snapshot()
    expected = sum(len(v["_GLOBAL_FUNCTIONS"]) for k, v in snapshot.items() if k != "<readers>")
    assert len(transforms) == expected
