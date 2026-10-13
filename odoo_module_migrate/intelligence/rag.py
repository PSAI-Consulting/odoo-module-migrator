# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Hybrid and auditable local RAG layer for Odoo migration.

Combines lexical BM25-style scoring with structural symbol extraction.
Strictly filters migration rules by version range, prioritizes curated rules,
indexes real target Odoo sources (Community, Enterprise, OCA),
preserves provenance, tracks budgets, and protects against prompt injection.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import pathlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .. import tools

logger = logging.getLogger(__name__)

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
    provenance: str  # path:start_line-end_line or path:line
    title: str
    content: str
    fingerprint: str = ""
    symbols: list[str] = field(default_factory=list)
    score: float = 0.0

    def __post_init__(self):
        if not self.fingerprint:
            raw = f"{self.chunk_type}:{self.provenance}:{self.content.strip()}"
            self.fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def render_tagged(self) -> str:
        """Render safely delimited chunk with verifiable provenance and fingerprint."""
        return (
            f'<retrieved_context type="{self.chunk_type}" source="{self.provenance}" '
            f'fingerprint="{self.fingerprint}" title="{self.title}">\n'
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
    for match in re.findall(r"\b[a-z][a-z0-9_]+(?:\.[a-z][a-z0-9_]+)+\b", text):
        symbols.add(match)
    for match in re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b", text):
        if "_" in match:
            symbols.add(match)
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

            steps = re.findall(r"migrate_(\d+)_(\d+)", rel_path)
            step_range = None
            if steps:
                step_range = (int(steps[0][0]), int(steps[0][1]))

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
    """Derive cache key recursively from all rule files."""
    package = pathlib.Path(__file__).parent.parent
    hasher = hashlib.sha256()

    policy_file = package / "knowledge" / "ollama_migration_policy.md"
    if policy_file.is_file():
        stat = policy_file.stat()
        hasher.update(f"{stat.st_mtime_ns}:{stat.st_size}".encode())

    rules_dir = package / "migration_scripts"
    if rules_dir.is_dir():
        for p in sorted(rules_dir.rglob("*")):
            if p.is_file() and p.suffix in {".yaml", ".py"}:
                stat = p.stat()
                hasher.update(f"{p.name}:{stat.st_mtime_ns}:{stat.st_size}".encode())

    key = hasher.hexdigest()[:16]
    return _load_cached_corpus(key, str(package))


class HybridRAG:
    """Retrieves targeted context, real target Odoo sources, and auditable rules."""

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
            getattr(module_report, "name", ""),
            *[f"{t.message} {getattr(t, 'source', '')}" for t in getattr(module_report, "todos", [])],
        ])
        self.query_tokens = set(_tokenize(self.query_text))
        self.query_symbols = set(_extract_symbols(self.query_text))

        self.retrieved_chunks: list[RAGChunk] = []

    def _score_tokens(self, chunk_tokens: set[str], chunk_symbols: list[str], is_curated: bool = False) -> float:
        """BM25-inspired scoring prioritizing exact symbol matches."""
        overlap = self.query_tokens.intersection(chunk_tokens)
        if not overlap and not (self.query_symbols.intersection(chunk_symbols)):
            return 0.0

        score = 0.0
        for tok in overlap:
            weight = 3.0 if ("." in tok or "_" in tok) else 1.0
            score += weight

        for sym in chunk_symbols:
            if sym in self.query_symbols:
                score += 15.0

        if is_curated:
            score *= 1.5

        return score

    def retrieve_target_sources(self, budget_chars: int = 3500) -> list[RAGChunk]:
        """Index and retrieve actual target Odoo definitions matching query symbols."""
        chunks: list[RAGChunk] = []
        if not self.query_symbols:
            return chunks

        all_target_dirs = [*self.reference_paths, *self.context_paths]
        used_chars = 0

        for base_dir in all_target_dirs:
            if not base_dir.is_dir():
                continue
            for ext in (".py", ".xml"):
                for p in tools.get_files(base_dir, (ext,)):
                    try:
                        content = tools._read_content(p)
                    except OSError:
                        continue

                    # Search matching symbol definitions
                    for sym in self.query_symbols:
                        if sym not in content:
                            continue
                        rel_path = p.relative_to(base_dir).as_posix() if base_dir in p.parents else p.name
                        lines = content.splitlines()

                        for line_idx, line_text in enumerate(lines):
                            if sym in line_text and any(kw in line_text for kw in ("class ", "fields.", "def ", "id=", "name=")):
                                start_idx = max(0, line_idx - 4)
                                end_idx = min(len(lines), line_idx + 12)
                                excerpt = "\n".join(lines[start_idx:end_idx])

                                chunk = RAGChunk(
                                    chunk_type="target_odoo",
                                    provenance=f"{rel_path}:{start_idx + 1}-{end_idx}",
                                    title=f"Source Odoo cible ({base_dir.name}/{rel_path})",
                                    content=excerpt,
                                    symbols=[sym],
                                    score=35.0,
                                )
                                if used_chars + len(excerpt) > budget_chars:
                                    return chunks
                                chunks.append(chunk)
                                used_chars += len(excerpt)
                                break
                        if used_chars >= budget_chars:
                            return chunks

        return chunks

    def retrieve_rules(self, budget_chars: int = 4500) -> list[RAGChunk]:
        """Retrieve relevant packaged migration rules filtered by version."""
        policy, corpus = _get_corpus()
        results: list[RAGChunk] = []

        if policy.strip():
            results.append(RAGChunk(
                chunk_type="documentation",
                provenance="knowledge/ollama_migration_policy.md:1",
                title="Politique de migration Odoo",
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

    def retrieve_module_sources(self, budget_chars: int = 4000) -> list[RAGChunk]:
        """Extract focused snippets from module files around diagnostics."""
        results: list[RAGChunk] = []
        m_path = getattr(self.module_report, "path", None)
        if not m_path or not pathlib.Path(m_path).is_dir():
            return results

        module_dir = pathlib.Path(m_path)
        used_chars = 0

        # Manifest
        manifest_path = next(
            (module_dir / name for name in ("__manifest__.py", "__openerp__.py") if (module_dir / name).is_file()),
            None,
        )
        if manifest_path:
            try:
                m_content = manifest_path.read_text(encoding="utf-8")
                results.append(RAGChunk(
                    chunk_type="module_source",
                    provenance=f"{manifest_path.name}:1",
                    title="Manifeste du module",
                    content=m_content[:1500],
                    score=50.0,
                ))
                used_chars += len(results[-1].content)
            except OSError as exc:
                logger.debug("Manifest read skipped: %s", exc)

        # Files from diagnostics
        for entry in getattr(self.module_report, "todos", []):
            if not getattr(entry, "file", None):
                continue
            path = module_dir / entry.file
            if not path.is_file():
                continue

            line = getattr(entry, "line", 1) or 1
            try:
                lines = tools._read_content(path).splitlines()
            except OSError:
                continue

            center = max(0, line - 1)
            start = max(0, center - 8)
            end = min(len(lines), center + 12)
            snippet = "\n".join(lines[start:end])

            chunk = RAGChunk(
                chunk_type="module_source",
                provenance=f"{entry.file}:{start + 1}-{end}",
                title=f"Extrait de {entry.file}:{line}",
                content=snippet,
                score=30.0,
            )
            if used_chars + len(snippet) > budget_chars:
                break
            results.append(chunk)
            used_chars += len(snippet)

        return results

    def build_prompt_context(self) -> tuple[str, str]:
        """Build sandbox-delimited prompt sections for rules, targets, and sources."""
        rule_chunks = self.retrieve_rules(budget_chars=4000)
        target_chunks = self.retrieve_target_sources(budget_chars=3000)
        source_chunks = self.retrieve_module_sources(budget_chars=3500)

        self.retrieved_chunks = [*rule_chunks, *target_chunks, *source_chunks]

        rules_str = "\n".join(c.render_tagged() for c in rule_chunks)
        if target_chunks:
            rules_str += "\n" + "\n".join(c.render_tagged() for c in target_chunks)

        sources_str = "\n".join(c.render_tagged() for c in source_chunks)
        return rules_str, sources_str

    def find_matching_chunk(self, evidence_str: str, proposed_op: dict[str, Any] | None = None) -> RAGChunk | None:
        """Find a verified RAG chunk corresponding to an evidence string or operation."""
        if not evidence_str and not proposed_op:
            return None

        clean_evidence = (evidence_str or "").strip().lower()

        for chunk in self.retrieved_chunks:
            # 1. Exact fingerprint match
            if chunk.fingerprint and chunk.fingerprint.lower() in clean_evidence:
                return chunk
            # 2. Exact provenance match (file:line)
            prov_norm = chunk.provenance.replace("\\", "/").lower()
            if prov_norm in clean_evidence or clean_evidence in prov_norm:
                return chunk
            # 3. Source content verification
            if proposed_op:
                old_val = str(proposed_op.get("old") or proposed_op.get("old_module") or proposed_op.get("old_key") or "")
                new_val = str(proposed_op.get("new") or proposed_op.get("new_module") or proposed_op.get("new_key") or "")
                if old_val and new_val and old_val in chunk.content and new_val in chunk.content:
                    return chunk

        return None
