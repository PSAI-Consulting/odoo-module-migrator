# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Reproducible evaluation of the retrieval used by the Ollama layer.

Each case is a deterministic finding with the rule (packaged in the migrator)
and the target definition (a small synthetic target addon) that should prove
its fix. The metrics are printed with ``pytest -s tests/test_rag_eval.py``
and asserted with floors, so a retrieval regression fails the suite.
"""

from __future__ import annotations

import os
import pathlib
import time

import pytest

from odoo_module_migrate import report
from odoo_module_migrate.intelligence.rag import HybridRAG, contains_symbol, rule_corpus

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "odoo_module_migrate" / "migration_scripts"


def _rule_line(rel, needle):
    for number, line in enumerate((PACKAGE / rel).read_text(encoding="utf-8").splitlines(), 1):
        if needle in line and not line.lstrip().startswith("#"):
            return f"migration_scripts/{rel}:{number}"
    raise AssertionError(f"{needle} not in {rel}")


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def world(tmp_path):
    target = tmp_path / "target"
    _write(target / "base/__manifest__.py", "{'name': 'base', 'depends': []}\n")
    _write(target / "sale/__manifest__.py", "{'name': 'sale', 'depends': ['base'], 'data': ['views/sale_views.xml']}\n")
    _write(target / "sale/models/sale_order_line.py",
           "from odoo import fields, models\n\n\nclass SaleOrderLine(models.Model):\n"
           "    _name = 'sale.order.line'\n\n    tax_ids = fields.Many2many('account.tax')\n")
    _write(target / "sale/report/sale_report.py",
           "class SaleReport(models.Model):\n    _name = 'sale.report'\n\n    def _select_dict(self):\n        return {}\n")
    _write(target / "sale/views/sale_views.xml",
           '<odoo><record id="view_order_form" model="ir.ui.view"><field name="arch" type="xml"><form>'
           '<field name="order_line"><list><field name="tax_ids"/></list></field></form></field></record></odoo>\n')
    _write(target / "mail_tracking/__manifest__.py", "{'name': 'mail_tracking', 'depends': ['base']}\n")
    module = tmp_path / "custom" / "my_sale"
    _write(module / "__manifest__.py", "{'name': 'my_sale', 'depends': ['sale']}\n")
    _write(module / "views/sale_order.xml",
           '<odoo>\n<record id="x" model="ir.ui.view">\n<field name="inherit_id" ref="sale.view_order_form"/>\n'
           '<field name="arch" type="xml">\n<xpath expr="//field[@name=\'tax_id\']" position="after"/>\n'
           '</field>\n</record>\n</odoo>\n')
    _write(module / "report/sale_report.py",
           "class SaleReport(models.Model):\n    _inherit = 'sale.report'\n\n"
           "    def _select_additional_fields(self):\n        return {}\n")
    _write(module / "models/tracking.py", "TRACKED = 'mail.tracking.value'\n")
    return target, module


CASES = [
    {
        "name": "renommage de champ standard / ancre XPath déplacée",
        "diag": ("ERROR", "[view] field[@name='tax_id'] not found in the combined view sale.view_order_form",
                 "views/sale_order.xml", 5),
        "proof": lambda: _rule_line("renamed_fields/migrate_180_190/generated.yaml", '"tax_id", "tax_ids"'),
        "target_symbol": "tax_ids",
    },
    {
        "name": "méthode renommée (API SQL des rapports)",
        "diag": ("WARNING", "Method sale.report._select_additional_fields is overridden but no longer exists in the target",
                 "report/sale_report.py", 4),
        "proof": lambda: _rule_line("renamed_methods/migrate_190_200/curated.yaml", "_select_additional_fields"),
        "target_symbol": "_select_dict",
    },
    {
        "name": "dépendance manquante",
        "diag": ("WARNING", ("[20] mail.tracking.value moved to the new module mail_tracking (odoo dd0c51ec1855): "
                             "add it to the depends"), "models/tracking.py", 1),
        "proof": lambda: _rule_line("text_warnings/migrate_190_200/odoo_20.yaml", "mail\\.tracking\\.value"),
        "target_symbol": None,
    },
]


def _rag(module, target, diag, enabled=True):
    rep = report.ModuleReport(module.name, module)
    entry = report.Entry(*diag)
    rag = HybridRAG(rep, "17.0", "20.0", reference_paths=[target], enabled=enabled)
    rag.build_prompt_context([entry], module, 10000)
    return rag


def test_rag_evaluation_metrics(world, capsys):
    target, module = world
    hits, proof_total, relevant_proofs, timings, target_hits, target_expected = 0, 0, 0, [], 0, 0
    lines = []
    for case in CASES:
        started = time.monotonic()
        rag = _rag(module, target, case["diag"])
        timings.append(time.monotonic() - started)
        proofs = [c for c in rag.retrieved_chunks if c.is_proof]
        expected = case["proof"]()
        rank = next((i + 1 for i, c in enumerate(proofs) if c.provenance == expected), None)
        hits += rank is not None and rank <= 5
        symbols = {w for w in case["diag"][1].replace("'", " ").replace("[", " ").replace("]", " ").split()
                   if "_" in w or "." in w}
        proof_total += len(proofs)
        relevant_proofs += sum(1 for c in proofs if any(contains_symbol(c.content, s.strip(".,:()@=")) for s in symbols))
        if case["target_symbol"]:
            target_expected += 1
            target_hits += any(c.chunk_type == "target_odoo" and contains_symbol(c.content, case["target_symbol"])
                               for c in rag.retrieved_chunks)
        off = _rag(module, target, case["diag"], enabled=False)
        assert not any(c.is_proof for c in off.retrieved_chunks)
        lines.append(f"{case['name']}: preuve attendue rang={rank}, {len(proofs)} preuve(s), "
                     f"{rag.stats['target']} définition(s) cible, RAG désactivé -> 0 preuve")
    metrics = {
        "hit@5": hits / len(CASES),
        "précision des preuves (mentionnent un symbole du diagnostic)": relevant_proofs / max(1, proof_total),
        "taux de faux chunks de preuve": 1 - relevant_proofs / max(1, proof_total),
        "définition cible retrouvée": target_hits / max(1, target_expected),
        "temps moyen (s)": sum(timings) / len(timings),
    }
    with capsys.disabled():
        print("\nÉvaluation RAG :")
        for line in lines:
            print("  -", line)
        for key, value in metrics.items():
            print(f"  {key} : {value:.2f}")
    assert metrics["hit@5"] == 1.0
    assert metrics["définition cible retrouvée"] == 1.0
    assert metrics["précision des preuves (mentionnent un symbole du diagnostic)"] >= 0.5


def test_version_interval_is_respected(world):
    target, module = world
    rag = _rag(module, target, ("WARNING", "Field calendar.alarm type should be alarm_type", "views/sale_order.xml", 1))
    for chunk in rag.retrieved_chunks:
        if chunk.chunk_type.startswith("rule_"):
            steps = [int(x) for x in __import__("re").findall(r"migrate_(\d+)_(\d+)", chunk.provenance)[-1]] \
                if "migrate_" in chunk.provenance and "allways" not in chunk.provenance else None
            assert steps is None or (170 <= steps[0] < steps[1] <= 200), chunk.provenance


def test_unverified_candidates_are_never_retrieved(world):
    target, module = world
    rag = _rag(module, target, ("ERROR", "Field account.account.group_id does not exist; parent_id?", "views/sale_order.xml", 1))
    assert not any("candidates" in c.provenance for c in rag.retrieved_chunks)
    assert not any("candidates" in item["rel_path"] for item in rule_corpus())


def test_fake_and_partial_proofs_do_not_match(world):
    target, module = world
    rag = _rag(module, target, CASES[0]["diag"])
    expected = CASES[0]["proof"]()
    assert rag.match_evidence([expected])
    for fake in (expected.rsplit(":", 1)[0], expected.split("/", 1)[1], "generated.yaml:25",
                 expected.replace(":", ":9"), "0123456789abcdef", "", "   "):
        assert rag.match_evidence([fake]) == [], fake


def test_absent_symbol_and_rule_target_conflict(world):
    target, module = world
    rag = _rag(module, target, ("ERROR", "Field sale.order.line.zz_nonexistent_field does not exist",
                                "views/sale_order.xml", 5))
    assert not any(c.chunk_type == "target_odoo" and "zz_nonexistent_field" in c.content for c in rag.retrieved_chunks)
    # The rule says tax_id -> tax_ids, but this target no longer defines tax_ids:
    # nothing may claim that the target confirms the new name.
    (target / "sale/models/sale_order_line.py").write_text("class L:\n    _name = 'sale.order.line'\n", encoding="utf-8")
    (target / "sale/views/sale_views.xml").write_text('<odoo><record id="view_order_form"/></odoo>\n', encoding="utf-8")
    conflicting = _rag(module, target, CASES[0]["diag"])
    assert not any(c.chunk_type == "target_odoo" and contains_symbol(c.content, "tax_ids")
                   for c in conflicting.retrieved_chunks)


def test_budget_and_context_modules(world, tmp_path):
    target, module = world
    context = tmp_path / "ctx"
    _write(context / "other/__manifest__.py", "{'name': 'other', 'depends': []}\n")
    rep = report.ModuleReport(module.name, module)
    rag = HybridRAG(rep, "17.0", "20.0", reference_paths=[target], context_paths=[context])
    rag.build_prompt_context([report.Entry(*CASES[0]["diag"])], module, 3000)
    assert sum(len(c.content) for c in rag.retrieved_chunks) <= 3000
    assert all(c.chunk_type != "target_odoo" or str(context) not in c.provenance for c in rag.retrieved_chunks)


def test_rule_cache_invalidated_by_nested_change(tmp_path):
    scripts = tmp_path / "odoo" / "upgrade_code"
    nested = scripts / "18.1-00-x.py"
    _write(nested, "def upgrade(file_manager):\n    old_marker = 1\n")
    assert any("old_marker" in i["body"] for i in rule_corpus(scripts))
    _write(nested, "def upgrade(file_manager):\n    new_marker_longer = 2\n")
    os.utime(nested, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
    bodies = [i["body"] for i in rule_corpus(scripts)]
    assert any("new_marker_longer" in b for b in bodies) and not any("old_marker" in b for b in bodies)


def test_upgrade_code_scripts_filtered_by_version(tmp_path, world):
    target, module = world
    scripts = tmp_path / "uc"
    _write(scripts / "17.5-01-tree-to-list.py", "def upgrade(fm):\n    # tax_id tree list\n    pass\n")
    _write(scripts / "16.4-00-old.py", "def upgrade(fm):\n    # tax_id ancient\n    pass\n")
    rep = report.ModuleReport(module.name, module)
    rag = HybridRAG(rep, "17.0", "20.0", reference_paths=[target], upgrade_code_dir=scripts)
    rag.build_prompt_context([report.Entry(*CASES[0]["diag"])], module, 10000)
    provenances = [c.provenance for c in rag.retrieved_chunks if c.chunk_type == "upgrade_code"]
    assert any("17.5-01" in p for p in provenances) and not any("16.4-00" in p for p in provenances)
