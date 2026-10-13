# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Objective confidence calculation based on verifiable evidence.

Never relies directly on the LLM's self-proclaimed confidence. Instead, computes
an internal multi-factor score from deterministic proofs:
- Official / curated rule match
- Target index symbol existence
- Precondition verified uniquely
- Typed structured applicator used
- Post-edit syntax validity
- Deterministic diagnostic elimination
- Absence of regressions
- Test and bench verification
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

    # 1. Syntax must be valid
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

    # Base points for clean unique syntax
    if is_unique_match:
        score += 0.20
        reasons.append("motif cible vérifié et unique")
    else:
        penalties.append("motif non unique ou introuvable")

    if syntax_valid:
        score += 0.15
        reasons.append("syntaxe validée (AST / XML / CSV)")

    # Official / Curated rule evidence
    lowered_evidence = (evidence_text + " " + rule_source).lower()
    if any(k in lowered_evidence for k in ("curated", "upgrade_code", "openupgrade", "commit odoo")):
        score += 0.25
        reasons.append("règle officielle ou vérifiée (curated / upgrade_code)")
    elif rule_source:
        score += 0.15
        reasons.append("règle du migrateur retrouvée")

    # Target symbol resolution
    if target_symbol_found:
        score += 0.15
        reasons.append("symbole résolu dans les sources cibles")

    # Diagnostic elimination
    if diagnostic_resolved:
        score += 0.15
        reasons.append("résout un diagnostic déterministe existant")

    # Applicator
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

    score = min(1.0, round(score, 2))

    # Tier determination
    if score >= 0.70 and is_unique_match and syntax_valid and not has_regressions:
        level = "haute"
        is_applicable = True
    elif score >= 0.45:
        level = "moyenne"
        is_applicable = False
    else:
        level = "faible"
        is_applicable = False

    return ConfidenceReport(
        score=score,
        level=level,
        reasons=reasons,
        penalties=penalties,
        is_applicable=is_applicable,
        validation_level=validation_level,
    )
