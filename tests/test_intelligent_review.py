# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import pytest

from odoo_module_migrate import intelligent_review, report
from odoo_module_migrate.__main__ import get_parser


def _module(tmp_path):
    root = tmp_path / "my_module"
    (root / "models").mkdir(parents=True)
    (root / "__manifest__.py").write_text(
        "{'name': 'My module', 'depends': ['base']}\n", encoding="utf-8"
    )
    (root / "models" / "partner.py").write_text(
        "from odoo import models\n\nclass Partner(models.Model):\n"
        "    _inherit = 'res.partner'\n    value = 1\n",
        encoding="utf-8",
    )
    rep = report.ModuleReport("my_module", root)
    rep.entries.append(report.Entry(
        "WARNING", "Check the migrated value", "models/partner.py", 5
    ))
    return root, rep


def test_retrieve_context_is_targeted_and_local(tmp_path):
    _root, rep = _module(tmp_path)
    context = intelligent_review.retrieve_context(rep, max_chars=10000)
    assert "__manifest__.py" in context
    assert "models/partner.py:5" in context
    assert "value = 1" in context


def test_rule_rag_loads_policy_and_real_migration_rules(tmp_path):
    _root, rep = _module(tmp_path)
    rep.entries[:] = [report.Entry(
        "WARNING",
        "Rename digits Product Unit of Measure to Product Unit",
        "models/partner.py",
        5,
    )]
    knowledge = intelligent_review.retrieve_rule_knowledge(rep, "18.0", "19.0")
    assert "Politique de relecture Odoo" in knowledge
    assert "Product Unit of Measure" in knowledge
    assert "migration_scripts/python_scripts/migrate_180_190/compatibility.py" in knowledge


def test_choose_model_prefers_coding_model(monkeypatch):
    monkeypatch.setattr(
        intelligent_review,
        "_request",
        lambda *args, **kwargs: {
            "models": [{"name": "llama3:8b"}, {"name": "qwen2.5-coder:7b"}]
        },
    )
    assert intelligent_review.choose_model() == "qwen2.5-coder:7b"


def test_review_module_uses_structured_local_request(tmp_path, monkeypatch):
    _root, rep = _module(tmp_path)
    calls = []

    def fake_request(url, path, payload=None, timeout=180):
        calls.append((url, path, payload))
        if path == "/api/tags":
            return {"models": [{"name": "qwen2.5-coder:7b"}]}
        return {"message": {"content": """{
          "summary": "Une vérification reste nécessaire.",
          "recommendations": [{
            "title": "Corriger la valeur", "diagnosis": "Valeur obsolète",
            "action": "Remplacer la constante", "confidence": "high",
            "file": "models/partner.py", "line": 5, "evidence": "value = 1",
            "edit": {"old": "value = 1", "new": "value = 2"}
          }]
        }"""}}

    monkeypatch.setattr(intelligent_review, "_request", fake_request)
    review = intelligent_review.review_module(rep, "17.0", "20.0")
    assert review.model == "qwen2.5-coder:7b"
    assert review.recommendations[0].old == "value = 1"
    assert calls[-1][1] == "/api/chat"
    assert calls[-1][2]["stream"] is False
    assert calls[-1][2]["format"]["type"] == "object"
    assert calls[-1][2]["options"]["num_ctx"] == 4096
    prompt = calls[-1][2]["messages"][-1]["content"]
    assert "RÈGLES DU MIGRATEUR RETROUVÉES (RAG LOCAL)" in prompt
    assert "Politique de relecture Odoo" in prompt


def test_review_refuses_non_local_url(tmp_path):
    _root, rep = _module(tmp_path)
    with pytest.raises(intelligent_review.OllamaError, match="locale"):
        intelligent_review.review_module(rep, "17.0", "20.0", url="https://example.com")


def test_apply_safe_exact_python_edit_and_reject_invalid(tmp_path):
    root, _rep = _module(tmp_path)
    # Unproven recommendation must be rejected without being written
    unproven = intelligent_review.Recommendation(
        "Unproven", "", "", "high", "models/partner.py", 5,
        old="value = 1", new="value = 99",
        evidence="",
    )
    # Proven recommendation with verified curated rule evidence is applicable
    valid = intelligent_review.Recommendation(
        "Safe", "", "", "high", "models/partner.py", 5,
        old="value = 1", new="value = 2",
        evidence="migration_scripts/curated.yaml:10",
    )
    invalid = intelligent_review.Recommendation(
        "Broken", "", "", "high", "models/partner.py", 5,
        old="value = 2", new="value = (",
        evidence="migration_scripts/curated.yaml:10",
    )
    review = intelligent_review.Review(recommendations=[unproven, valid, invalid])
    intelligent_review.apply_safe_edits(root, review)
    text = (root / "models" / "partner.py").read_text(encoding="utf-8")
    assert "value = 99" not in text
    assert "value = 2" in text
    assert "confiance objective insuffisante" in unproven.status
    assert valid.status == "applied"
    assert invalid.status.startswith("rejected: syntaxe invalide")


def test_advice_only_fact_check_rejects_hallucinated_snippet(tmp_path):
    root, _rep = _module(tmp_path)
    item = intelligent_review.Recommendation(
        "Invented", "", "", "high", "__manifest__.py", 1,
        old='version": "20.0.0.1"', new='version": "20.0.0.0"',
    )
    review = intelligent_review.Review(recommendations=[item])
    intelligent_review.assess_safe_edits(root, review)
    assert item.status == "rejected: texte attendu non unique ou absent"


def test_report_renders_intelligent_review(tmp_path):
    _root, rep = _module(tmp_path)
    rep.intelligent_review = intelligent_review.Review(
        model="qwen2.5-coder:7b",
        summary="Résumé clair.",
        recommendations=[intelligent_review.Recommendation(
            "Vérifier", "Cause", "Action", "medium", "models/partner.py", 5
        )],
    )
    text = report.render(rep, "17.0", "20.0")
    assert "## Relecture intelligente locale" in text
    assert "Résumé clair." in text
    assert "Confiance :** moyenne" in text


def test_cli_exposes_ollama_options():
    args = get_parser().parse_args([
        "-i", "17.0", "-t", "20.0", "--ollama", "--ollama-model", "coder:7b"
    ])
    assert args.ollama_review is True
    assert args.ollama_model == "coder:7b"
