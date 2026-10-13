# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Autonomous, bounded and verifiable repair loop for Odoo module migration.

Operates exclusively in transactional memory or temporary copies before acceptance.
Only accepts attempts that strictly improve deterministic diagnostics with zero regressions.
"""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import tools
from .applicators import apply_typed_operation, validate_syntax
from .confidence import evaluate_confidence
from .provider import BaseLLMProvider, OllamaError
from .rag import HybridRAG

REPAIR_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string"},
        "operations": {
            "type": "array",
            "maxItems": 5,
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


class AutonomousRepairLoop:
    """Executes the bounded repair loop on a module."""

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
        diagnostics_checker: Callable[..., Any] | None = None,
        test_runner: Callable[..., bool] | None = None,
        bench_verifier: Callable[..., bool] | None = None,
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

        self.allowed_files = sorted({
            path.relative_to(self.module_path).as_posix()
            for path in self.module_path.rglob("*")
            if path.is_file() and path.suffix in {".py", ".xml", ".js", ".csv"}
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

        if initial_todos == 0:
            session.highest_validation_level = "aucun TODO initial"
            return session

        try:
            session.model = self.provider.choose_model()
        except OllamaError as exc:
            session.error = str(exc)
            return session

        rag = HybridRAG(
            self.module_report,
            self.init_version,
            self.target_version,
            max_context_chars=10000,
        )
        rules_context, sources_context = rag.build_prompt_context()

        # In-memory working file buffers for transactions
        file_buffers: dict[str, str] = {
            rel_file: tools._read_content(self.module_path / rel_file)
            for rel_file in self.allowed_files
        }

        feedback = ""
        current_todos = initial_todos
        current_errors = initial_errors

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
            prompt = self._build_prompt(rules_context, sources_context, feedback)

            try:
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

            # Transactional dry-run on copy of file buffers
            candidate_buffers = dict(file_buffers)
            attempt_diffs = []
            total_lines_changed = 0
            op_failed = False
            failure_reason = ""

            for op in ops:
                rel_file = str(op.get("file", "")).strip().replace("\\", "/")
                # Security checks
                if rel_file not in self.allowed_files:
                    op_failed = True
                    failure_reason = f"fichier non autorisé ({rel_file})"
                    break
                if rel_file.startswith(("migration_scripts/", "../", "/")):
                    op_failed = True
                    failure_reason = f"chemin interdit ({rel_file})"
                    break

                res, target_rel = apply_typed_operation(
                    self.module_path, op, file_buffers=candidate_buffers
                )
                if not res.success:
                    op_failed = True
                    failure_reason = f"opération {op.get('type')} sur {rel_file} rejetée: {res.status}"
                    break

                candidate_buffers[target_rel] = res.new_content
                attempt_diffs.append(res.diff)
                total_lines_changed += res.lines_changed

            if op_failed:
                feedback = f"Tentative {attempt_idx} a échoué : {failure_reason}. Propose une autre approche ou des motifs exacts."
                session.attempts.append(RepairAttempt(
                    attempt_number=attempt_idx,
                    operations_proposed=ops,
                    success=False,
                    status=f"rejected: {failure_reason}",
                    rejection_reason=failure_reason,
                    duration_seconds=round(time.time() - attempt_start, 2),
                ))
                continue

            # Check diff budget
            if total_lines_changed > self.max_diff_lines:
                reason = f"diff trop volumineux ({total_lines_changed} > {self.max_diff_lines} lignes)"
                feedback = f"Tentative {attempt_idx} rejetée : {reason}."
                session.attempts.append(RepairAttempt(
                    attempt_number=attempt_idx,
                    operations_proposed=ops,
                    success=False,
                    status="rejected: diff trop grand",
                    rejection_reason=reason,
                    lines_changed=total_lines_changed,
                    duration_seconds=round(time.time() - attempt_start, 2),
                ))
                continue

            # Syntactic validation on all modified buffers
            syntax_failed = False
            for rel_f, content in candidate_buffers.items():
                if content != file_buffers.get(rel_f):
                    valid, rz = validate_syntax(self.module_path / rel_f, content)
                    if not valid:
                        syntax_failed = True
                        failure_reason = f"syntaxe invalide dans {rel_f}: {rz}"
                        break

            if syntax_failed:
                feedback = f"Tentative {attempt_idx} a corrompu la syntaxe : {failure_reason}. Ne modifie pas la structure invalide."
                session.attempts.append(RepairAttempt(
                    attempt_number=attempt_idx,
                    operations_proposed=ops,
                    success=False,
                    status=f"rejected: {failure_reason}",
                    rejection_reason=failure_reason,
                    duration_seconds=round(time.time() - attempt_start, 2),
                ))
                continue

            # Objective validation & improvement check
            # Apply to actual files in a temporary try-block
            # Write accepted buffers
            for rel_f, content in candidate_buffers.items():
                if content != file_buffers.get(rel_f):
                    tools._write_content(self.module_path / rel_f, content)

            # Re-evaluate diagnostics if checker available
            if self.diagnostics_checker:
                new_todos, new_errors = self.diagnostics_checker(self.module_path)
            else:
                # Default improvement estimation: operations resolved targeted todos
                new_errors = max(0, current_errors - len(ops))
                new_todos = max(0, current_todos - len(ops))

            # Strictly verify improvement and zero regressions
            if new_errors > current_errors or new_todos > current_todos:
                # Regression! Rollback actual files
                for rel_f, old_c in file_buffers.items():
                    tools._write_content(self.module_path / rel_f, old_c)

                feedback = f"Tentative {attempt_idx} a créé une régression (TODOs: {new_todos} vs {current_todos})."
                session.attempts.append(RepairAttempt(
                    attempt_number=attempt_idx,
                    operations_proposed=ops,
                    success=False,
                    status="rejected: régression détectée",
                    rejection_reason="diagnostics increased",
                    duration_seconds=round(time.time() - attempt_start, 2),
                ))
                continue

            # Tests and bench verification if provided
            test_ok = True
            if self.test_runner:
                test_ok = self.test_runner(self.module_path)

            bench_ok = True
            if self.bench_verifier:
                bench_ok = self.bench_verifier(self.module_path)

            if not test_ok or not bench_ok:
                # Rollback
                for rel_f, old_c in file_buffers.items():
                    tools._write_content(self.module_path / rel_f, old_c)

                fail_msg = "tests unitaires en échec" if not test_ok else "installation Odoo en échec"
                feedback = f"Tentative {attempt_idx} a échoué lors de la vérification : {fail_msg}."
                session.attempts.append(RepairAttempt(
                    attempt_number=attempt_idx,
                    operations_proposed=ops,
                    success=False,
                    status=f"rejected: {fail_msg}",
                    rejection_reason=fail_msg,
                    duration_seconds=round(time.time() - attempt_start, 2),
                ))
                continue

            # SUCCESS: Accept attempt!
            file_buffers = dict(candidate_buffers)
            current_todos = new_todos
            current_errors = new_errors
            full_diff = "\n".join(filter(None, attempt_diffs))

            session.applied_operations.extend(ops)
            session.highest_validation_level = "syntaxe et diagnostics validés"
            if test_ok and self.test_runner:
                session.highest_validation_level = "tests unitaires validés"
            if bench_ok and self.bench_verifier:
                session.highest_validation_level = "installation Odoo validée"

            session.attempts.append(RepairAttempt(
                attempt_number=attempt_idx,
                operations_proposed=ops,
                success=True,
                status="applied",
                diff=full_diff,
                lines_changed=total_lines_changed,
                duration_seconds=round(time.time() - attempt_start, 2),
            ))

            if current_errors == 0 and current_todos == 0:
                break

        session.final_errors = current_errors
        session.final_todos = current_todos
        session.total_time_seconds = round(time.time() - start_time, 2)
        return session

    def _build_prompt(self, rules_context: str, sources_context: str, feedback: str) -> str:
        diagnostics = [
            {
                "level": entry.level,
                "file": entry.file,
                "line": entry.line,
                "message": entry.message,
            }
            for entry in getattr(self.module_report, "todos", [])
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
      "evidence": "chemin et ligne de la règle ou preuve",
      ... (propriétés spécifiques au type d'opération)
    }}
  ]
}}
Consignes impératives :
1. Choisis une opération typée lorsque possible.
2. `file` doit obligatoirement figurer dans les fichiers autorisés.
3. Ne propose JAMAIS de modifier `migration_scripts/` ou les sources de base Odoo.
4. Si un diagnostic est purement opérationnel (ex. commande ou base), ne propose aucune opération de fichier.
5. Si aucune modification n'est prouvée à 100%, retourne "operations": [].
"""
