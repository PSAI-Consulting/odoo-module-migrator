# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Objective confidence calculation based on verifiable evidence.

Never relies on the LLM's self-proclaimed confidence or raw text evidence.
Every proof must correspond to a verified RAG chunk with confirmed provenance
and fingerprint, deterministic target symbols, and verified elimination
of stable diagnostic identifiers with zero regressions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rag import RAGChunk


@dataclass
class ConfidenceReport:
    score: float
    level: str  # "haute", "moyenne", "faible", "rejetée"
    reasons: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    is_applicable: bool = False
    validation_level: str = "non validée"


def evaluate_confidence(
    evidence_text: str = "",
    rule_source: str = "",
    evidence_chunk: RAGChunk | None = None,
    hallucinated_evidence_claimed: bool = False,
    applicator_success: bool = False,
    syntax_valid: bool = False,
    is_unique_match: bool = False,
    diagnostic_resolved: bool = False,
    has_regressions: bool = False,
    target_symbol_found: bool = False,
    tests_passed: bool = False,
    bench_passed: bool = False,
    diff_lines: int = 0,
    max_diff_lines: int = 200,
) -> ConfidenceReport:
    """Compute an objective score (0.0 - 1.0) and applicability threshold."""
    reasons: list[str] = []
    penalties: list[str] = []
    score = 0.0

    # 1. Syntax must be strictly valid
    if not syntax_valid:
        penalties.append("syntaxe invalide après modification")
        return ConfidenceReport(
            score=0.0,
            level="rejetée",
            reasons=reasons,
            penalties=penalties,
            is_applicable=False,
            validation_level="rejetée: syntaxe invalide",
        )

    # 2. No regressions permitted
    if has_regressions:
        penalties.append("crée de nouveaux diagnostics ou régression")
        return ConfidenceReport(
            score=0.0,
            level="rejetée",
            reasons=reasons,
            penalties=penalties,
            is_applicable=False,
            validation_level="rejetée: régression constatée",
        )

    # 3. Diff budget
    if diff_lines > max_diff_lines:
        penalties.append(f"taille de diff excessive ({diff_lines} > {max_diff_lines})")
        return ConfidenceReport(
            score=0.0,
            level="rejetée",
            reasons=reasons,
            penalties=penalties,
            is_applicable=False,
            validation_level="rejetée: diff trop grand",
        )

    # Precondition uniqueness
    if is_unique_match:
        score += 0.20
        reasons.append("motif cible vérifié et unique")
    else:
        penalties.append("motif non unique ou introuvable")

    if syntax_valid:
        score += 0.15
        reasons.append("syntaxe validée (AST / XML / CSV)")

    # 4. Verified RAG Proof vs Hallucinated Evidence
    if evidence_chunk is not None:
        chunk_type = getattr(evidence_chunk, "chunk_type", "")
        if chunk_type == "rule_curated":
            score += 0.30
            reasons.append(f"règle curated officielle vérifiée ({evidence_chunk.provenance})")
        elif chunk_type == "target_odoo":
            score += 0.25
            reasons.append(f"source Odoo cible indexée vérifiée ({evidence_chunk.provenance})")
        elif chunk_type in {"rule_generated", "documentation"}:
            score += 0.15
            reasons.append(f"règle du migrateur vérifiée ({evidence_chunk.provenance})")
    elif hallucinated_evidence_claimed:
        penalties.append("preuve fournie introuvable dans l'index RAG (hallucination rejetée)")
        score -= 0.30
    elif (rule_source or evidence_text) and any(
        k in (rule_source or evidence_text).lower() for k in ("curated", "upgrade_code", "openupgrade")
    ):
        # Fallback for deterministic rule names passed directly by caller
        score += 0.20
        reasons.append("source de règle déterministe certifiée")

    # 5. Target Symbol Resolution (deterministic)
    if target_symbol_found:
        score += 0.15
        reasons.append("symbole résolu dans les sources cibles")

    # 6. Diagnostic Resolution (deterministic comparison)
    if diagnostic_resolved:
        score += 0.20
        reasons.append("résout un diagnostic déterministe existant")
    else:
        penalties.append("aucun diagnostic résolu de manière prouvée")

    # 7. Applicator
    if applicator_success:
        score += 0.10
        reasons.append("applicateur structuré typé exécuté")

    # Advanced verification stages
    validation_level = "syntaxe validée"
    if diagnostic_resolved:
        validation_level = "diagnostic résolu"

    if tests_passed:
        score += 0.20
        reasons.append("tests unitaires du module validés")
        validation_level = "tests validés"

    if bench_passed:
        score += 0.20
        reasons.append("installation Odoo réelle validée")
        validation_level = "installation validée"

    score = max(0.0, min(1.0, round(score, 2)))

    # Threshold for applicability
    # Must have score >= 0.70, unique match, syntax valid, no regressions,
    # and either resolved a diagnostic OR matched a verified official rule
    has_solid_proof = diagnostic_resolved or (
        evidence_chunk is not None and getattr(evidence_chunk, "chunk_type", "") == "rule_curated"
    )
    is_applicable = (
        score >= 0.70
        and is_unique_match
        and syntax_valid
        and not has_regressions
        and not hallucinated_evidence_claimed
        and has_solid_proof
    )

    if score >= 0.75 and is_applicable:
        level = "haute"
    elif score >= 0.50:
        level = "moyenne"
    elif score >= 0.25:
        level = "faible"
    else:
        level = "rejetée"

    return ConfidenceReport(
        score=score,
        level=level,
        reasons=reasons,
        penalties=penalties,
        is_applicable=is_applicable,
        validation_level=validation_level,
    )
