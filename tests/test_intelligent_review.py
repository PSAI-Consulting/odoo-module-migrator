# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Review (--ollama) and verified application (--ollama-apply) of model edits."""

import json
import re

import pytest

from odoo_module_migrate import intelligent_review, report
from odoo_module_migrate.__main__ import get_parser
from odoo_module_migrate.intelligence.diagnostics import FullModuleDiagnosticsChecker
from odoo_module_migrate.intelligence.provider import BaseLLMProvider, ProviderStats

RULE_MESSAGE = "[20] ReadonlyDict is deprecated since 20.0: use odoo.tools.frozendict"


class ScriptedProvider(BaseLLMProvider):
    """Fake local model: answers are produced from the prompt it receives."""

    def __init__(self, answer):
        self.answer = answer
        self.stats = ProviderStats()
        self.prompts = []

    def list_models(self):
        return []

    def choose_model(self, requested=""):
        return "fake-coder:7b"

    def chat(self, messages, **kwargs):
        self.prompts.append(messages[-1]["content"])
        return self.answer(messages[-1]["content"]) if callable(self.answer) else self.answer


def _module(tmp_path, body="from odoo.tools import ReadonlyDict\n\nDISCOUNT = 10\n"):
    root = tmp_path / "my_module"
    (root / "models").mkdir(parents=True)
    (root / "__manifest__.py").write_text("{'name': 'My module', 'depends': ['base']}\n", encoding="utf-8")
    (root / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    (root / "models" / "__init__.py").write_text("from . import partner\n", encoding="utf-8")
    (root / "models" / "partner.py").write_text(body, encoding="utf-8")
    rep = report.ModuleReport("my_module", root)
    rep.entries.append(report.Entry("WARNING", RULE_MESSAGE, "models/partner.py", 1))
    return root, rep


def _checker(root):
    from odoo_module_migrate.migration import Migration

    migration = Migration(root.parent, "17.0", "20.0", [root.name], commit_enabled=False, pre_commit=False)
    return FullModuleDiagnosticsChecker("20.0", migration._migration_scripts, init_version="17.0").check_module


def _rule_ref(prompt, needle="ReadonlyDict"):
    """`source` attribute of the retrieved rule block mentioning ``needle``."""
    for match in re.finditer(r'<ctx_[0-9a-f]+ type="(rule_\w+)" ref="(\w+)" source="([^"]+)"[^>]*>\n(.*?)\n</ctx_', prompt, re.DOTALL):
        if needle in match.group(4):
            return match.group(3)
    raise AssertionError("rule block not retrieved")


def _review(tmp_path, recommendations, body=None):
    root, rep = _module(tmp_path, body) if body else _module(tmp_path)

    def answer(prompt):
        recs = recommendations(prompt) if callable(recommendations) else recommendations
        return {"summary": "Résumé.", "recommendations": recs}

    provider = ScriptedProvider(answer)
    review = intelligent_review.review_module(rep, "17.0", "20.0", provider=provider)
    return root, rep, review, provider


def _rec(old, new, evidence, title="Renommer"):
    return {"title": title, "diagnosis": "d", "action": "a", "confidence": "high", "file": "models/partner.py",
            "line": 1, "evidence": evidence, "edit": {"old": old, "new": new}}


def test_review_prompt_is_local_tagged_and_bounded(tmp_path):
    _root, _rep, review, provider = _review(tmp_path, [])
    prompt = provider.prompts[0]
    assert "ReadonlyDict" in prompt and "models/partner.py" in prompt
    assert review.rag is not None and review.rag.stats["proof_chunks"] >= 1
    assert re.search(r"<ctx_[0-9a-f]{8} ", prompt)
    assert len(prompt) < 30000


def test_review_refuses_non_local_url(tmp_path):
    _root, rep = _module(tmp_path)
    with pytest.raises(intelligent_review.OllamaError, match="locale"):
        intelligent_review.review_module(rep, "17.0", "20.0", url="https://example.com")


def test_verified_edit_is_applied_with_real_score(tmp_path):
    root, _rep, review, _provider = _review(
        tmp_path, lambda p: [_rec("import ReadonlyDict", "import frozendict", [_rule_ref(p)])]
    )
    intelligent_review.apply_safe_edits(root, review, checker=_checker(root))
    item = review.recommendations[0]
    assert item.status == "applied", item.status
    assert "import frozendict" in (root / "models" / "partner.py").read_text(encoding="utf-8")
    assert item.objective_score == pytest.approx(sum(f.weight for f in item.factors if f.satisfied))
    assert item.objective_confidence in {"haute", "moyenne"}
    assert item.resolved and item.resolved[0][2] == RULE_MESSAGE


def test_review_mode_verifies_but_never_writes(tmp_path):
    root, _rep, review, _provider = _review(
        tmp_path, lambda p: [_rec("import ReadonlyDict", "import frozendict", [_rule_ref(p)])]
    )
    before = (root / "models" / "partner.py").read_bytes()
    intelligent_review.assess_safe_edits(root, review, checker=_checker(root))
    assert review.recommendations[0].status.startswith("proposed")
    assert (root / "models" / "partner.py").read_bytes() == before


@pytest.mark.parametrize("evidence", [[], ["curated"], ["openupgrade_rules:1"], ["migration_scripts/curated.yaml:10"],
                                      ["knowledge/ollama_migration_policy.md:1"]])
def test_invented_or_empty_evidence_never_applies(tmp_path, evidence):
    root, _rep, review, _provider = _review(
        tmp_path, [_rec("import ReadonlyDict", "import frozendict", evidence)]
    )
    intelligent_review.apply_safe_edits(root, review, checker=_checker(root))
    assert review.recommendations[0].status.startswith("rejected")
    assert "ReadonlyDict" in (root / "models" / "partner.py").read_text(encoding="utf-8")


def test_business_constant_change_is_rejected_even_with_valid_proof(tmp_path):
    root, _rep, review, _provider = _review(
        tmp_path, lambda p: [_rec("DISCOUNT = 10", "DISCOUNT = 0", [_rule_ref(p)])]
    )
    intelligent_review.apply_safe_edits(root, review, checker=_checker(root))
    assert "renommage de symboles" in review.recommendations[0].status
    assert "DISCOUNT = 10" in (root / "models" / "partner.py").read_text(encoding="utf-8")


def test_only_the_operation_resolving_a_diagnostic_is_applied(tmp_path):
    body = "from odoo.tools import ReadonlyDict\n\nDISCOUNT_NAME = 'discount'\n"
    root, _rep, review, _provider = _review(tmp_path, lambda p: [
        _rec("'discount'", "'rebate'", [_rule_ref(p)], "rename sans diagnostic"),
        _rec("import ReadonlyDict", "import frozendict", [_rule_ref(p)], "correction"),
        _rec("import frozendict", "import frozendict as fd", [_rule_ref(p)], "profite de la précédente"),
    ], body=body)
    intelligent_review.apply_safe_edits(root, review, checker=_checker(root))
    first, second, third = review.recommendations
    assert first.status.startswith("rejected") and "diagnostic" in first.status
    assert second.status == "applied"
    assert third.status.startswith("rejected")
    text = (root / "models" / "partner.py").read_text(encoding="utf-8")
    assert "'discount'" in text and "import frozendict\n" in text


def test_edit_without_checker_stays_advice(tmp_path):
    root, _rep, review, _provider = _review(
        tmp_path, lambda p: [_rec("import ReadonlyDict", "import frozendict", [_rule_ref(p)])]
    )
    intelligent_review.apply_safe_edits(root, review)
    assert "non vérifiable" in review.recommendations[0].status
    assert "ReadonlyDict" in (root / "models" / "partner.py").read_text(encoding="utf-8")


def test_hallucinated_snippet_rejected(tmp_path):
    root, _rep, review, _provider = _review(tmp_path, lambda p: [_rec("version 20.0.0.1", "x", [_rule_ref(p)])])
    intelligent_review.assess_safe_edits(root, review, checker=_checker(root))
    assert "texte attendu absent" in review.recommendations[0].status


def test_report_never_fabricates_a_score(tmp_path):
    _root, rep = _module(tmp_path)
    rep.intelligent_review = intelligent_review.Review(
        model="qwen2.5-coder:7b", summary="Résumé clair.",
        recommendations=[intelligent_review.Recommendation("Vérifier", "Cause", "Action", "high", "models/partner.py", 5)],
    )
    text = report.render(rep, "17.0", "20.0")
    assert "## Assistance IA locale (Ollama)" in text and "Résumé clair." in text
    assert "aucun score calculé" in text
    assert "Auto-évaluation du modèle (non prise en compte) :** high" in text
    assert "Confiance objective :** haute" not in text


def test_report_shows_rejections_factors_and_coverage(tmp_path):
    root, rep, review, _provider = _review(
        tmp_path, lambda p: [_rec("import ReadonlyDict", "import frozendict", [_rule_ref(p)])]
    )
    intelligent_review.assess_safe_edits(root, review, checker=_checker(root))
    review.coverage = [("vues", False, "sources non indexées"), ("syntaxe", True, "")]
    rep.intelligent_review = review
    text = report.render(rep, "17.0", "20.0")
    assert "➖ non rejouée vues — sources non indexées" in text
    assert "Facteurs du score" in text and "(obligatoire)" in text
    assert "migration_scripts/text_warnings/migrate_190_200/odoo_20.yaml:" in text
    assert "tests = skipped" in text and "tests = passed" not in text


def test_offline_ollama_is_reported_without_todo(tmp_path):
    from odoo_module_migrate.migration import Migration

    _module(tmp_path)
    migration = Migration(tmp_path, "17.0", "20.0", ["my_module"], commit_enabled=False, pre_commit=False,
                          write_report=True, ollama_review=True, ollama_url="http://127.0.0.1:9")
    migration.run()
    rep = migration.report_collector.reports["my_module"]
    assert rep.intelligent_review.error
    assert not any("Ollama" in e.message for e in rep.todos)


def test_migration_apply_mode_end_to_end(tmp_path, monkeypatch):
    from odoo_module_migrate.migration import Migration

    root, _rep = _module(tmp_path)

    def fake_chat(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        return {"summary": "s", "recommendations": [
            _rec("import ReadonlyDict", "import frozendict", [_rule_ref(prompt)]),
            _rec("DISCOUNT = 10", "DISCOUNT = 0", ["openupgrade_rules:1"]),
        ]}

    monkeypatch.setattr("odoo_module_migrate.intelligence.provider.OllamaProvider.choose_model",
                        lambda self, requested="": "fake-coder:7b")
    monkeypatch.setattr("odoo_module_migrate.intelligence.provider.OllamaProvider.chat", fake_chat)
    monkeypatch.setattr("odoo_module_migrate.intelligence.provider.OllamaProvider.context_budget",
                        lambda self, model="", num_predict=1024: 20000)
    migration = Migration(tmp_path, "17.0", "20.0", ["my_module"], commit_enabled=False, pre_commit=False,
                          write_report=True, ollama_apply=True)
    migration.run()
    text = (root / "models" / "partner.py").read_text(encoding="utf-8")
    assert "frozendict" in text and "DISCOUNT = 10" in text
    rep = migration.report_collector.reports["my_module"]
    assert not any(e.message == RULE_MESSAGE for e in rep.todos)
    statuses = [r.status for r in rep.intelligent_review.recommendations]
    assert statuses[0] == "applied" and statuses[1].startswith("rejected")
    rendered = (root / report.REPORT_NAME).read_text(encoding="utf-8")
    assert "appliquée après vérification déterministe" in rendered


def test_cli_exposes_ollama_options():
    args = get_parser().parse_args([
        "-i", "17.0", "-t", "20.0", "--ollama", "--ollama-model", "coder:7b"
    ])
    assert args.ollama_review is True
    assert args.ollama_model == "coder:7b"


def test_normalize_tolerates_malformed_items():
    review = intelligent_review._normalize({"summary": 1, "recommendations": [
        "text", {"line": "x", "confidence": "sure", "evidence": ["a", "b"], "edit": "no"},
    ]}, "m")
    item = review.recommendations[0]
    assert item.line == 0 and item.confidence == "medium" and item.evidence == "a b" and item.old == ""
    assert json.dumps(item.title)
