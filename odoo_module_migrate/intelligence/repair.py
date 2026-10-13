# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Autonomous, bounded and verifiable repair loop for Odoo module migration.

Operates exclusively in an isolated temporary directory before acceptance.
Only accepts attempts that strictly improve deterministic diagnostics with
zero regressions, verified by the full diagnostic checker.
Never modifies actual module files on failures, regressions or exceptions.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import tools
from .applicators import apply_typed_operation, validate_syntax
from .confidence import evaluate_confidence
from .diagnostics import stable_diagnostic_id
from .provider import BaseLLMProvider, OllamaError
from .rag import HybridRAG

logger = logging.getLogger(__name__)

REPAIR_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string"},
        "operations": {
            "type": "array",
            "maxItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "exact_text_replace",
                            "replace_import",
                            "add_import",
                            "rename_dict_key",
                            "xml_set_attribute",
                            "xml_replace_xpath",
                            "manifest_add_dependency",
                            "csv_replace_value",
                        ],
                    },
                    "file": {"type": "string"},
                    "description": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                    "old_module": {"type": "string"},
                    "new_module": {"type": "string"},
                    "name": {"type": "string"},
                    "module": {"type": "string"},
                    "old_key": {"type": "string"},
                    "new_key": {"type": "string"},
                    "line": {"type": "integer"},
                    "tag": {"type": "string"},
                    "attribute": {"type": "string"},
                    "old_value": {"type": "string"},
                    "new_value": {"type": "string"},
                    "identifier": {"type": "string"},
                    "old_expr": {"type": "string"},
                    "new_expr": {"type": "string"},
                    "dependency": {"type": "string"},
                    "column": {"type": "integer"},
                    "evidence": {"type": "string"},
                },
                "required": ["type", "file"],
            },
        },
    },
    "required": ["analysis", "operations"],
}


@dataclass
class VerificationResult:
    status: str  # "passed", "failed", "skipped"
    message: str = ""


@dataclass
class RepairAttempt:
    attempt_number: int
    operations_proposed: list[dict[str, Any]]
    success: bool
    status: str
    rejection_reason: str = ""
    diff: str = ""
    lines_changed: int = 0
    duration_seconds: float = 0.0


@dataclass
class RepairSession:
    module_name: str
    model: str
    attempts: list[RepairAttempt] = field(default_factory=list)
    applied_operations: list[dict[str, Any]] = field(default_factory=list)
    initial_errors: int = 0
    initial_todos: int = 0
    final_errors: int = 0
    final_todos: int = 0
    total_time_seconds: float = 0.0
    highest_validation_level: str = "non validée"
    error: str = ""


def publish_changes_atomically(
    module_path: pathlib.Path,
    temp_module: pathlib.Path,
    allowed_files: list[str],
) -> list[str]:
    """Atomically publish modified files from temp_module to module_path.

    1. Snapshots in-memory backups of all destination files to be overwritten.
    2. Writes changes to temporary sibling files and replaces targets via os.replace.
    3. In case of any error during write, completely restores all original files.
    """
    module_path = pathlib.Path(module_path).resolve()
    temp_module = pathlib.Path(temp_module).resolve()

    changed_map: dict[str, bytes] = {}
    for rel_f in allowed_files:
        temp_f = temp_module / rel_f
        orig_f = module_path / rel_f
        if temp_f.is_file():
            temp_bytes = temp_f.read_bytes()
            orig_bytes = orig_f.read_bytes() if orig_f.is_file() else b""
            if temp_bytes != orig_bytes:
                changed_map[rel_f] = temp_bytes

    if not changed_map:
        return []

    # Snapshot in-memory backups of all files to be replaced
    backups: dict[str, bytes | None] = {}
    for rel_f in changed_map:
        orig_f = module_path / rel_f
        backups[rel_f] = orig_f.read_bytes() if orig_f.is_file() else None

    written_files: list[str] = []
    tmp_files: list[pathlib.Path] = []

    try:
        for rel_f, new_bytes in changed_map.items():
            target_f = module_path / rel_f
            target_f.parent.mkdir(parents=True, exist_ok=True)
            tmp_f = target_f.with_name(f".tmp_repair_{target_f.name}")
            tmp_files.append(tmp_f)
            tmp_f.write_bytes(new_bytes)
            os.replace(tmp_f, target_f)
            written_files.append(rel_f)
    except Exception as exc:
        # Atomic rollback: restore all original files
        for rel_f in written_files:
            target_f = module_path / rel_f
            orig_bytes = backups.get(rel_f)
            if orig_bytes is not None:
                target_f.write_bytes(orig_bytes)
            elif target_f.exists():
                try:
                    target_f.unlink()
                except OSError:
                    pass
        for tmp_f in tmp_files:
            if tmp_f.exists():
                try:
                    tmp_f.unlink()
                except OSError:
                    pass
        raise RuntimeError(f"Échec atomique lors de la publication des modifications : {exc}") from exc
    finally:
        for tmp_f in tmp_files:
            if tmp_f.exists():
                try:
                    tmp_f.unlink()
                except OSError:
                    pass

    return list(changed_map.keys())


class AutonomousRepairLoop:
    """Executes the bounded, transactional repair loop on a module copy."""

    def __init__(
        self,
        module_path: pathlib.Path,
        module_report: Any,
        init_version: str,
        target_version: str,
        provider: BaseLLMProvider,
        *,
        max_attempts: int = 3,
        max_minutes: int = 20,
        max_diff_lines: int = 200,
        diagnostics_checker: Callable[[pathlib.Path], list[Any]] | None = None,
        test_runner: Callable[[pathlib.Path], Any] | None = None,
        bench_verifier: Callable[[pathlib.Path], Any] | None = None,
        rag: HybridRAG | None = None,
        known_modules: set[str] | None = None,
        dependency_graph: dict[str, list[str]] | None = None,
        target_view_tree: Any | None = None,
    ):
        self.module_path = pathlib.Path(module_path).resolve()
        self.module_report = module_report
        self.init_version = init_version
        self.target_version = target_version
        self.provider = provider
        self.max_attempts = max(1, min(max_attempts, 10))
        self.max_seconds = max_minutes * 60
        self.max_diff_lines = max_diff_lines
        self.diagnostics_checker = diagnostics_checker
        self.test_runner = test_runner
        self.bench_verifier = bench_verifier
        self.rag = rag
        self.known_modules = known_modules
        self.dependency_graph = dependency_graph
        self.target_view_tree = target_view_tree

        self.allowed_files = sorted({
            path.relative_to(self.module_path).as_posix()
            for path in self.module_path.rglob("*")
            if path.is_file() and path.suffix in {".py", ".xml", ".csv"}
        })

    def run(self) -> RepairSession:
        start_time = time.time()
        initial_todos = len(getattr(self.module_report, "todos", []))
        initial_errors = len(getattr(self.module_report, "errors", []))

        session = RepairSession(
            module_name=getattr(self.module_report, "name", self.module_path.name),
            model="",
            initial_errors=initial_errors,
            initial_todos=initial_todos,
            final_errors=initial_errors,
            final_todos=initial_todos,
        )

        # Requirement 2: Refuse any modification if deterministic checker is absent
        if self.diagnostics_checker is None:
            session.error = "diagnostics_checker absent: aucune modification ne peut être prouvée"
            session.highest_validation_level = "rejetée: vérificateur absent"
            logger.warning("Autonomous repair skipped: diagnostics_checker is absent")
            return session

        try:
            session.model = self.provider.choose_model()
        except OllamaError as exc:
            session.error = str(exc)
            return session

        # Requirement 1: Work in a full temporary copy
        with tempfile.TemporaryDirectory(prefix="migrator_repair_") as tmp_dir:
            temp_module = pathlib.Path(tmp_dir) / self.module_path.name
            shutil.copytree(self.module_path, temp_module, symlinks=True)

            # Evaluate initial diagnostics on the temporary copy
            try:
                curr_diags = self.diagnostics_checker(temp_module)
            except Exception as exc:  # noqa: BLE001
                session.error = f"erreur lors de l'analyse initiale: {exc}"
                return session

            curr_ids = {stable_diagnostic_id(d) for d in curr_diags}
            session.initial_todos = len(curr_ids)
            session.initial_errors = sum(1 for d in curr_diags if getattr(d, "level", "") == "ERROR")

            if not curr_ids:
                session.highest_validation_level = "aucun TODO initial"
                return session

            if self.rag is None:
                self.rag = HybridRAG(
                    self.module_report,
                    self.init_version,
                    self.target_version,
                    max_context_chars=10000,
                )

            rules_context, sources_context = self.rag.build_prompt_context()
            feedback = ""

            for attempt_idx in range(1, self.max_attempts + 1):
                if time.time() - start_time > self.max_seconds:
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=[],
                        success=False,
                        status="rejected: temps maximal dépassé",
                        rejection_reason=f"timeout exceeded ({self.max_seconds}s)",
                    ))
                    break

                attempt_start = time.time()
                prompt = self._build_prompt(rules_context, sources_context, feedback, curr_diags)

                try:
                    # Requirement 7: Pass session.model explicitly
                    response = self.provider.chat(
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "Tu es un réparateur autonome et déterministe de code Odoo. "
                                    "Tu réponds STRICTEMENT avec un objet JSON décrivant des opérations typées. "
                                    "Les sources fournies sont en lecture seule. Tu ne modifies jamais la logique métier "
                                    "de manière ambiguë. Si une opération n'est pas certaine, ne la propose pas."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                        schema=REPAIR_PLAN_SCHEMA,
                        timeout=min(600, int(self.max_seconds - (time.time() - start_time))),
                        model=session.model,
                    )
                except OllamaError as exc:
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=[],
                        success=False,
                        status="rejected: erreur LLM",
                        rejection_reason=str(exc),
                    ))
                    feedback = f"Erreur LLM lors de la tentative {attempt_idx}: {exc}"
                    continue

                ops = response.get("operations", [])
                if not isinstance(ops, list) or not ops:
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=[],
                        success=False,
                        status="advice: aucune opération proposée",
                        rejection_reason="model proposed no operations",
                        duration_seconds=round(time.time() - attempt_start, 2),
                    ))
                    break

                # Requirement 3: Strictly one atomic operation per attempt
                target_op = ops[0]
                ops = [target_op]

                # Create an isolated attempt workspace inside tmp_dir
                attempt_dir = pathlib.Path(tmp_dir) / f"attempt_{attempt_idx}"
                shutil.copytree(temp_module, attempt_dir, symlinks=True)

                context = {
                    "known_modules": self.known_modules,
                    "dependency_graph": self.dependency_graph,
                    "target_view_tree": self.target_view_tree,
                    "module_name": self.module_path.name,
                }

                rel_file = str(target_op.get("file", "")).strip().replace("\\", "/")
                if rel_file.endswith(".js"):
                    feedback = f"Tentative {attempt_idx} rejetée : modification automatique JavaScript interdite."
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=ops,
                        success=False,
                        status="rejected: modification automatique JavaScript interdite",
                        rejection_reason="JS auto-application forbidden",
                        duration_seconds=round(time.time() - attempt_start, 2),
                    ))
                    continue

                if rel_file not in self.allowed_files:
                    feedback = f"Tentative {attempt_idx} rejetée : fichier non autorisé ({rel_file})."
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=ops,
                        success=False,
                        status=f"rejected: fichier non autorisé ({rel_file})",
                        rejection_reason=f"file {rel_file} not in editable module files",
                        duration_seconds=round(time.time() - attempt_start, 2),
                    ))
                    continue

                res, _ = apply_typed_operation(attempt_dir, target_op, context=context)
                if not res.success:
                    failure_reason = f"opération {target_op.get('type')} sur {rel_file} rejetée: {res.status}"
                    feedback = f"Tentative {attempt_idx} rejetée : {failure_reason}."
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=ops,
                        success=False,
                        status=f"rejected: {failure_reason}",
                        rejection_reason=failure_reason,
                        duration_seconds=round(time.time() - attempt_start, 2),
                    ))
                    continue

                # Write immediately to attempt_dir
                target_file = attempt_dir / rel_file
                tools._write_content(target_file, res.new_content)

                if res.lines_changed > self.max_diff_lines:
                    reason = f"diff trop volumineux ({res.lines_changed} > {self.max_diff_lines} lignes)"
                    feedback = f"Tentative {attempt_idx} rejetée : {reason}."
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=ops,
                        success=False,
                        status="rejected: diff trop grand",
                        rejection_reason=reason,
                        lines_changed=res.lines_changed,
                        duration_seconds=round(time.time() - attempt_start, 2),
                    ))
                    continue

                # Syntax verification on the modified file
                valid, rz = validate_syntax(target_file, res.new_content)
                if not valid:
                    failure_reason = f"syntaxe invalide dans {rel_file}: {rz}"
                    feedback = f"Tentative {attempt_idx} a corrompu la syntaxe : {failure_reason}."
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=ops,
                        success=False,
                        status=f"rejected: {failure_reason}",
                        rejection_reason=failure_reason,
                        duration_seconds=round(time.time() - attempt_start, 2),
                    ))
                    continue

                # Requirement 3: Re-run full diagnostics on attempt_dir
                try:
                    new_diags = self.diagnostics_checker(attempt_dir)
                except Exception as exc:  # noqa: BLE001
                    feedback = f"Erreur lors du contrôle des diagnostics : {exc}."
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=ops,
                        success=False,
                        status="rejected: exception dans le vérificateur",
                        rejection_reason=str(exc),
                        duration_seconds=round(time.time() - attempt_start, 2),
                    ))
                    continue

                new_ids = {stable_diagnostic_id(d) for d in new_diags}
                added_ids = new_ids - curr_ids
                resolved_ids = curr_ids - new_ids

                # Requirement 2: Strict zero-regression and elimination of at least 1 diagnostic
                if added_ids:
                    feedback = f"Tentative {attempt_idx} a créé {len(added_ids)} nouveau(x) diagnostic(s) : {list(added_ids)[:2]}."
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=ops,
                        success=False,
                        status="rejected: régression détectée",
                        rejection_reason=f"{len(added_ids)} nouveaux diagnostics",
                        duration_seconds=round(time.time() - attempt_start, 2),
                    ))
                    continue

                if not resolved_ids:
                    feedback = f"Tentative {attempt_idx} n'a résolu aucun diagnostic ciblé."
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=ops,
                        success=False,
                        status="rejected: aucune amélioration prouvée",
                        rejection_reason="diagnostics inchangés",
                        duration_seconds=round(time.time() - attempt_start, 2),
                    ))
                    continue

                # Requirement 3: Attribute resolved diagnostic IDs strictly to this atomic operation
                target_op["resolved_diagnostic_ids"] = list(resolved_ids)

                # Requirement 4: Verify confidence for this single operation
                ev_chunk = self.rag.find_matching_chunk(target_op.get("evidence", ""), target_op)
                hallucinated = bool(target_op.get("evidence")) and (ev_chunk is None)
                conf = evaluate_confidence(
                    evidence_chunk=ev_chunk,
                    hallucinated_evidence_claimed=hallucinated,
                    applicator_success=True,
                    syntax_valid=True,
                    is_unique_match=True,
                    diagnostic_resolved=True,
                    has_regressions=False,
                    diff_lines=res.lines_changed,
                    max_diff_lines=self.max_diff_lines,
                )
                if not conf.is_applicable:
                    failure_reason = f"confiance non applicable pour {target_op.get('type')} (score {conf.score}, {conf.level})"
                    feedback = f"Tentative {attempt_idx} rejetée par le contrôle de confiance : {failure_reason}."
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=ops,
                        success=False,
                        status=f"rejected: {failure_reason}",
                        rejection_reason=failure_reason,
                        duration_seconds=round(time.time() - attempt_start, 2),
                    ))
                    continue

                # Requirement 7: Test runner with passed / failed / skipped distinction
                test_status = "skipped"
                if self.test_runner:
                    try:
                        tr_res = self.test_runner(attempt_dir)
                        if isinstance(tr_res, VerificationResult):
                            test_status = tr_res.status
                        elif isinstance(tr_res, bool):
                            test_status = "passed" if tr_res else "failed"
                        else:
                            test_status = str(tr_res)
                    except Exception as exc:  # noqa: BLE001
                        test_status = "failed"
                        failure_reason = f"exception test runner: {exc}"

                if test_status == "failed":
                    feedback = f"Tentative {attempt_idx} a échoué aux tests unitaires : {failure_reason}."
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=ops,
                        success=False,
                        status="rejected: tests unitaires en échec",
                        rejection_reason="test suite failed",
                        duration_seconds=round(time.time() - attempt_start, 2),
                    ))
                    continue

                # Requirement 7: Bench verifier with passed / failed / skipped distinction
                bench_status = "skipped"
                if self.bench_verifier:
                    try:
                        bv_res = self.bench_verifier(attempt_dir)
                        if isinstance(bv_res, VerificationResult):
                            bench_status = bv_res.status
                        elif isinstance(bv_res, bool):
                            bench_status = "passed" if bv_res else "failed"
                        else:
                            bench_status = str(bv_res)
                    except Exception as exc:  # noqa: BLE001
                        bench_status = "failed"
                        failure_reason = f"exception bench verifier: {exc}"

                if bench_status == "failed":
                    feedback = f"Tentative {attempt_idx} a échoué à l'installation Odoo : {failure_reason}."
                    session.attempts.append(RepairAttempt(
                        attempt_number=attempt_idx,
                        operations_proposed=ops,
                        success=False,
                        status="rejected: installation Odoo en échec",
                        rejection_reason="bench installation failed",
                        duration_seconds=round(time.time() - attempt_start, 2),
                    ))
                    continue

                # Requirement 8: Store actual ConfidenceReport and scores directly on operation
                target_op["confidence_report"] = conf
                target_op["objective_score"] = conf.score
                target_op["objective_confidence"] = conf.level
                target_op["validation_level"] = conf.validation_level

                # SUCCESS! Accept attempt and update temp_module
                shutil.rmtree(temp_module)
                shutil.copytree(attempt_dir, temp_module, symlinks=True)

                curr_ids = new_ids
                curr_diags = new_diags
                session.applied_operations.append(target_op)

                if bench_status == "passed":
                    session.highest_validation_level = "installation Odoo validée"
                elif test_status == "passed":
                    session.highest_validation_level = "tests unitaires validés"
                else:
                    session.highest_validation_level = "syntaxe et diagnostics validés"

                session.attempts.append(RepairAttempt(
                    attempt_number=attempt_idx,
                    operations_proposed=ops,
                    success=True,
                    status="applied",
                    diff=res.diff,
                    lines_changed=res.lines_changed,
                    duration_seconds=round(time.time() - attempt_start, 2),
                ))

                if not curr_ids:
                    break

            # Requirement 1 & 4: Commit to actual module path ONLY if changes were proven, with atomic replacement
            if session.applied_operations:
                try:
                    publish_changes_atomically(
                        self.module_path, temp_module, self.allowed_files
                    )
                except Exception as exc:  # noqa: BLE001
                    session.error = f"erreur lors de la publication atomique: {exc}"
                    logger.error("Atomic publication failed: %s", exc)

            session.final_todos = len(curr_ids)
            session.final_errors = sum(1 for d in curr_diags if getattr(d, "level", "") == "ERROR")
            session.total_time_seconds = round(time.time() - start_time, 2)
            return session

    def _build_prompt(
        self,
        rules_context: str,
        sources_context: str,
        feedback: str,
        current_diags: list[Any],
    ) -> str:
        diagnostics = [
            {
                "level": getattr(d, "level", "WARNING"),
                "file": getattr(d, "file", ""),
                "line": getattr(d, "line", 0),
                "message": getattr(d, "message", ""),
            }
            for d in current_diags
        ]
        transformations = [
            t.message for t in getattr(self.module_report, "transformations", [])
        ]

        feedback_section = ""
        if feedback:
            feedback_section = f"\n<feedback_tentative_precedente>\n{feedback}\n</feedback_tentative_precedente>\n"

        return f"""Construis un plan de réparation autonome et typé pour le module `{self.module_report.name}`
(migration {self.init_version} vers {self.target_version}).

<diagnostics_a_reparer>
{json.dumps(diagnostics, ensure_ascii=False, indent=2)}
</diagnostics_a_reparer>

<transformations_deja_appliquees>
{json.dumps(transformations, ensure_ascii=False, indent=2)}
</transformations_deja_appliquees>

<fichiers_du_module_autorises>
{json.dumps(self.allowed_files, ensure_ascii=False)}
</fichiers_du_module_autorises>
{feedback_section}
<regles_migration_retrouvees>
{rules_context}
</regles_migration_retrouvees>

<sources_du_module>
{sources_context}
</sources_du_module>

Réponds STRICTEMENT avec un objet JSON au schéma suivant :
{{
  "analysis": "analyse concise du problème et justification",
  "operations": [
    {{
      "type": "exact_text_replace|replace_import|add_import|rename_dict_key|xml_set_attribute|xml_replace_xpath|manifest_add_dependency|csv_replace_value",
      "file": "chemin relatif parmi les fichiers autorisés",
      "description": "explication concise",
      "evidence": "chemin, ligne ou empreinte de la règle prouvée",
      ... (propriétés spécifiques au type d'opération)
    }}
  ]
}}
Consignes impératives :
1. Choisis une opération typée lorsque possible.
2. `file` doit obligatoirement figurer dans les fichiers autorisés (pas de .js).
3. Ne propose JAMAIS de modifier `migration_scripts/` ou les sources de base Odoo.
4. Si un diagnostic est purement opérationnel, ne propose aucune opération de fichier.
5. Si aucune modification n'est prouvée à 100%, retourne "operations": [].
"""
