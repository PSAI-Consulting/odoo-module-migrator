# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Hybrid and auditable local RAG layer for Odoo migration.

Combines lexical BM25-style scoring with structural symbol extraction.
Strictly filters migration rules by version range, prioritizes curated rules,
preserves provenance, tracks budgets, and protects against prompt injection.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import math
import os
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .. import tools

_STOP_WORDS = {
    "a", "about", "after", "against", "all", "an", "and", "any", "are", "as",
    "at", "aucun", "aussi", "avec", "avant", "be", "been", "but", "by", "ce",
    "ces", "cet", "cette", "check", "dans", "de", "depuis", "des", "detected",
    "doit", "du", "elle", "en", "error", "est", "et", "field", "file", "for",
    "from", "has", "have", "il", "ils", "in", "is", "it", "la", "le", "les",
    "leur", "mais", "migration", "model", "module", "ne", "no", "not", "odoo",
    "of", "on", "or", "ou", "par", "pas", "plus", "pour", "que", "qui", "requires",
    "sa", "se", "ses", "son", "sont", "source", "sur", "target", "the", "this",
    "to", "todo", "un", "une", "version", "view", "warning", "was", "with",
}


@dataclass
class RAGChunk:
    chunk_type: str  # diagnostic | module_source | target_odoo | rule_curated | rule_generated | documentation | applied_transformation
    provenance: str  # path:line
    title: str
    content: str
    symbols: list[str] = field(default_factory=list)
    score: float = 0.0

    def render_tagged(self) -> str:
        """Render safely delimited chunk."""
        return (
            f'<retrieved_context type="{self.chunk_type}" source="{self.provenance}" title="{self.title}">\n'
            f"{self.content}\n"
            f"</retrieved_context>"
        )


def _tokenize(text: str) -> list[str]:
    """Extract normalized tokens from code and diagnostic text."""
    return [
        t.lower()
        for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_.]{2,}", text)
        if t.lower() not in _STOP_WORDS and not t.isdigit()
    ]


def _extract_symbols(text: str) -> list[str]:
    """Find specific Odoo symbols like models, fields, methods, XML IDs."""
    symbols = set()
    # Model names: e.g. res.partner, stock.picking, account.move.line
    for match in re.findall(r"\b[a-z][a-z0-9_]+(?:\.[a-z][a-z0-9_]+)+\b", text):
        symbols.add(match)
    # Identifiers with underscores: e.g. uom_id, product_uom, _select_seller
    for match in re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b", text):
        if "_" in match:
            symbols.add(match)
    # XML IDs: e.g. module.view_id
    for match in re.findall(r"\b[a-z0-9_]+\.[a-z0-9_]+\b", text):
        symbols.add(match)
    return sorted(symbols)


@functools.lru_cache(maxsize=4)
def _load_cached_corpus(cache_key: str, package_dir_str: str) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Load policy and migration rules corpus, caching in memory."""
    package = pathlib.Path(package_dir_str)
    policy_path = package / "knowledge" / "ollama_migration_policy.md"
    policy = policy_path.read_text(encoding="utf-8") if policy_path.is_file() else ""

    rules_dir = package / "migration_scripts"
    chunks = []
    if rules_dir.is_dir():
        for path in sorted((*rules_dir.rglob("*.yaml"), *rules_dir.rglob("*.py"))):
            if path.name == "__init__.py":
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()
            except OSError:
                continue

            rel_path = path.relative_to(package).as_posix()
            is_curated = "curated.yaml" in rel_path or "curated" in path.name
            rule_type = "rule_curated" if is_curated else "rule_generated"

            # Parse steps
            steps = re.findall(r"migrate_(\d+)_(\d+)", rel_path)
            step_range = None
            if steps:
                step_range = (int(steps[0][0]), int(steps[0][1]))

            # Slide over lines with overlap
            step_size = 16
            window_size = 24
            for start in range(0, len(lines), step_size):
                chunk_lines = lines[start:start + window_size]
                body = "\n".join(chunk_lines).strip()
                if not body:
                    continue
                symbols = _extract_symbols(body)
                tokens = _tokenize(body)
                chunks.append({
                    "type": rule_type,
                    "rel_path": rel_path,
                    "line": start + 1,
                    "body": body,
                    "symbols": symbols,
                    "tokens": set(tokens),
                    "step_range": step_range,
                    "is_curated": is_curated,
                })

    return policy, tuple(chunks)


def _get_corpus() -> tuple[str, tuple[dict[str, Any], ...]]:
    package = pathlib.Path(__file__).parent.parent
    # Derive hash from modtimes
    hasher = hashlib.sha256()
    rules_dir = package / "migration_scripts"
    if rules_dir.is_dir():
        for p in sorted(rules_dir.glob("*")):
            hasher.update(str(p.stat().st_mtime_ns).encode("utf-8"))
    key = hasher.hexdigest()[:16]
    return _load_cached_corpus(key, str(package))


class HybridRAG:
    """Retrieves targeted context and auditable migration rules for a module."""

    def __init__(
        self,
        module_report: Any,
        init_version: str,
        target_version: str,
        *,
        reference_paths: Iterable[pathlib.Path | str] = (),
        context_paths: Iterable[pathlib.Path | str] = (),
        max_context_chars: int = 10000,
    ):
        self.module_report = module_report
        self.init_version = init_version
        self.target_version = target_version
        self.init_code = int(float(init_version) * 10)
        self.target_code = int(float(target_version) * 10)
        self.reference_paths = [pathlib.Path(p).resolve() for p in reference_paths if p]
        self.context_paths = [pathlib.Path(p).resolve() for p in context_paths if p]
        self.max_context_chars = max_context_chars

        # Build query profile
        self.query_text = " ".join([
            module_report.name,
            *[f"{t.message} {t.source}" for t in getattr(module_report, "todos", [])],
        ])
        self.query_tokens = set(_tokenize(self.query_text))
        self.query_symbols = set(_extract_symbols(self.query_text))

    def _score_tokens(self, chunk_tokens: set[str], chunk_symbols: list[str], is_curated: bool = False) -> float:
        """BM25-inspired scoring prioritizing exact symbol matches."""
        overlap = self.query_tokens.intersection(chunk_tokens)
        if not overlap and not (self.query_symbols.intersection(chunk_symbols)):
            return 0.0

        score = 0.0
        # Token weight
        for tok in overlap:
            weight = 3.0 if ("." in tok or "_" in tok) else 1.0
            score += weight

        # Symbol match boost
        for sym in chunk_symbols:
            if sym in self.query_symbols:
                score += 15.0

        if is_curated:
            score *= 1.5

        return score

    def retrieve_rules(self, budget_chars: int = 5000) -> list[RAGChunk]:
        """Retrieve relevant packaged migration rules filtered by version."""
        policy, corpus = _get_corpus()
        results: list[RAGChunk] = []

        if policy.strip():
            results.append(RAGChunk(
                chunk_type="documentation",
                provenance="knowledge/ollama_migration_policy.md:1",
                title="Politique de relecture Odoo",
                content=policy.strip(),
                score=100.0,
            ))

        ranked: list[tuple[float, dict[str, Any]]] = []
        for item in corpus:
            step_range = item["step_range"]
            if step_range:
                start_step, end_step = step_range
                # Strict version interval filtering
                if not (self.init_code <= start_step < end_step <= self.target_code):
                    continue

            score = self._score_tokens(item["tokens"], item["symbols"], is_curated=item["is_curated"])
            if score > 0.0:
                ranked.append((score, item))

        ranked.sort(key=lambda x: -x[0])

        used_chars = sum(len(c.content) for c in results)
        seen_bodies = set()

        for score, item in ranked:
            body = item["body"]
            body_hash = hashlib.md5(body.encode("utf-8")).hexdigest()
            if body_hash in seen_bodies:
                continue
            seen_bodies.add(body_hash)

            chunk = RAGChunk(
                chunk_type=item["type"],
                provenance=f"{item['rel_path']}:{item['line']}",
                title=f"Règle de migration ({item['rel_path']})",
                content=body,
                symbols=item["symbols"],
                score=score,
            )
            if used_chars + len(body) > budget_chars:
                break
            results.append(chunk)
            used_chars += len(body)
            if len(results) >= 8:
                break

        return results

    def retrieve_module_sources(self, budget_chars: int = 8000) -> list[RAGChunk]:
        """Retrieve module files focusing on diagnostic lines."""
        results: list[RAGChunk] = []
        module_path = getattr(self.module_report, "path", None)
        if not module_path or not module_path.is_dir():
            return results

        # 1. Manifest
        manifest_path = next(
            (module_path / name for name in ("__manifest__.py", "__openerp__.py")
             if (module_path / name).is_file()),
            None,
        )
        if manifest_path:
            try:
                manifest_text = tools._read_content(manifest_path)
                results.append(RAGChunk(
                    chunk_type="module_source",
                    provenance=f"{manifest_path.name}:1",
                    title="Manifeste du module",
                    content=manifest_text[:3000],
                    score=50.0,
                ))
            except Exception:
                pass

        # 2. Files from diagnostics
        seen_locations = set()
        candidates: list[tuple[pathlib.Path, int, str]] = []
        for todo in getattr(self.module_report, "todos", []):
            if not getattr(todo, "file", None):
                continue
            fpath = (module_path / todo.file).resolve()
            try:
                fpath.relative_to(module_path.resolve())
            except ValueError:
                continue
            candidates.append((fpath, getattr(todo, "line", 1) or 1, todo.message))

        # 3. Supplemental module sources
        for path in sorted(module_path.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".xml", ".csv"}:
                candidates.append((path.resolve(), 1, "source du module"))

        used_chars = sum(len(c.content) for c in results)

        for path, line, reason in candidates:
            loc_key = (str(path), line)
            if loc_key in seen_locations or not path.is_file():
                continue
            seen_locations.add(loc_key)

            try:
                lines = tools._read_content(path).splitlines()
            except Exception:
                continue

            center = max(0, line - 1)
            radius = 12 if "source du module" not in reason else 35
            start = max(0, center - radius)
            end = min(len(lines), center + radius + 1)
            snippet = "\n".join(f"{i + 1:>5}: {lines[i]}" for i in range(start, end))

            rel_file = path.relative_to(module_path).as_posix()
            chunk = RAGChunk(
                chunk_type="module_source",
                provenance=f"{rel_file}:{line}",
                title=f"Source ({rel_file}) - {reason}",
                content=snippet,
                symbols=_extract_symbols(snippet),
                score=10.0 if "source du module" not in reason else 2.0,
            )

            if used_chars + len(snippet) > budget_chars:
                break
            results.append(chunk)
            used_chars += len(snippet)
            if len(results) >= 12:
                break

        return results

    def build_prompt_context(self) -> tuple[str, str]:
        """Return (tagged_rules_string, tagged_sources_string)."""
        rule_budget = min(6000, max(2500, self.max_context_chars // 2))
        source_budget = max(3000, self.max_context_chars - rule_budget)

        rule_chunks = self.retrieve_rules(budget_chars=rule_budget)
        source_chunks = self.retrieve_module_sources(budget_chars=source_budget)

        rules_rendered = "\n\n".join(c.render_tagged() for c in rule_chunks)
        sources_rendered = "\n\n".join(c.render_tagged() for c in source_chunks)

        return rules_rendered, sources_rendered
