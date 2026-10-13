# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Objective confidence of an automatic edit, computed from verified facts only.

The model's own confidence and its free-text "evidence" never count. Each
factor below is established by deterministic code; the report lists them all.

Mandatory conditions (``is_applicable``) — any missing one blocks the edit:

* the typed applicator found exactly one target and produced valid syntax;
* the structural guard proved a pure symbol rewrite;
* the deterministic replay shows at least one diagnostic of the edited file
  resolved (any file for a manifest dependency) and no new diagnostic;
* the evidence references a retrieved *proof* chunk (curated or generated
  rule, official upgrade_code script) that mentions every symbol the edit
  removes and introduces;
* evidence referenced by the model but absent from the retrieved chunks is a
  fabricated proof: rejection;
* tests and installation, when they ran, did not fail.

The score is the sum of the weights of the satisfied factors; it is reported,
never assumed. ``haute`` requires an applicable edit and a score >= 0.85.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rag import RAGChunk

PROOF_WEIGHTS = {"rule_curated": 0.25, "upgrade_code": 0.25, "rule_generated": 0.20}


@dataclass
class ConfidenceFactor:
    name: str
    weight: float
    satisfied: bool
    mandatory: bool
    detail: str = ""


@dataclass
class ConfidenceReport:
    score: float
    level: str  # "haute", "moyenne", "non applicable"
    reasons: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    is_applicable: bool = False
    validation_level: str = "non validée"
    factors: list[ConfidenceFactor] = field(default_factory=list)


def evaluate_confidence(
    *,
    applicator_success: bool = False,
    unique_target: bool = False,
    syntax_valid: bool = False,
    symbol_rewrite: bool = False,
    resolved_diagnostics: int = 0,
    resolved_in_scope: bool = False,
    new_diagnostics: int = 0,
    proof_chunk: RAGChunk | None = None,
    proof_relevant: bool = False,
    proof_missing: tuple[str, ...] = (),
    fabricated_evidence: bool = False,
    target_symbol_found: bool = False,
    tests_status: str = "skipped",
    bench_status: str = "skipped",
    diff_lines: int = 0,
    max_diff_lines: int = 200,
) -> ConfidenceReport:
    proof_type = getattr(proof_chunk, "chunk_type", "")
    proof_weight = PROOF_WEIGHTS.get(proof_type, 0.0)
    proof_detail = (
        f"{proof_type} {proof_chunk.provenance}" if proof_chunk is not None else "aucune référence de preuve vérifiée"
    )
    if proof_chunk is not None and getattr(proof_chunk, "rule", None):
        # reported only: the weights do not change, a structured verified
        # rule does not open new automatic edits (Lot A)
        proof_detail += (" (règle structurée vérifiée)" if proof_chunk.proof_strength == "strong"
                         else " (règle historique, preuve non structurée)")
    if proof_chunk is not None and not proof_relevant:
        proof_detail += " (ne mentionne pas : " + ", ".join(proof_missing) + ")"
    factors = [
        ConfidenceFactor("applicateur typé : cible unique trouvée", 0.10,
                         applicator_success and unique_target, True),
        ConfidenceFactor("syntaxe valide après édition", 0.10, syntax_valid, True),
        ConfidenceFactor("renommage de symboles uniquement (structure inchangée)", 0.15, symbol_rewrite, True),
        ConfidenceFactor(
            "diagnostic déterministe résolu dans le périmètre de l'édition", 0.25,
            resolved_diagnostics > 0 and resolved_in_scope, True,
            f"{resolved_diagnostics} résolu(s)",
        ),
        ConfidenceFactor("aucun nouveau diagnostic", 0.0, new_diagnostics == 0, True,
                         f"{new_diagnostics} nouveau(x)" if new_diagnostics else ""),
        ConfidenceFactor(
            "preuve vérifiée et pertinente (règle ou script officiel)", proof_weight or 0.20,
            bool(proof_weight) and proof_relevant, True, proof_detail,
        ),
        ConfidenceFactor("aucune preuve inventée", 0.0, not fabricated_evidence, True),
        ConfidenceFactor("symbole introduit présent dans les sources cibles", 0.10, target_symbol_found, False),
        ConfidenceFactor(f"diff borné ({diff_lines}/{max_diff_lines} lignes)", 0.0, diff_lines <= max_diff_lines, True),
        ConfidenceFactor("tests du module", 0.05, tests_status == "passed", False, tests_status),
        ConfidenceFactor("installation Odoo", 0.05, bench_status == "passed", False, bench_status),
    ]
    if tests_status == "failed":
        factors.append(ConfidenceFactor("tests du module en échec", 0.0, False, True))
    if bench_status == "failed":
        factors.append(ConfidenceFactor("installation Odoo en échec", 0.0, False, True))

    score = round(min(1.0, sum(f.weight for f in factors if f.satisfied)), 2)
    is_applicable = all(f.satisfied for f in factors if f.mandatory)
    reasons = [f.name + (f" ({f.detail})" if f.detail else "") for f in factors if f.satisfied and f.weight]
    penalties = [f.name + (f" ({f.detail})" if f.detail else "") for f in factors if not f.satisfied]
    if not is_applicable:
        level = "non applicable"
    elif score >= 0.85:
        level = "haute"
    else:
        level = "moyenne"

    if bench_status == "passed":
        validation_level = "installation Odoo réussie"
    elif tests_status == "passed":
        validation_level = "tests du module passés"
    elif resolved_diagnostics and not new_diagnostics:
        validation_level = "diagnostic résolu par réanalyse déterministe"
    elif syntax_valid:
        validation_level = "syntaxe seule"
    else:
        validation_level = "non validée"
    return ConfidenceReport(
        score=score,
        level=level,
        reasons=reasons,
        penalties=penalties,
        is_applicable=is_applicable,
        validation_level=validation_level,
        factors=factors,
    )
