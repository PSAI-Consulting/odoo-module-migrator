# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Model-independent provider abstraction for local LLMs.

Loopback-only, any installed model can be chosen explicitly (no closed list),
the context window is sized from the actual prompt and bounded by the model
and the machine, and every call records its timings for the optional metrics.
"""

from __future__ import annotations

import abc
import functools
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .system_profile import (
    ModelProfile,
    SystemHardware,
    context_cap,
    detect_hardware,
    parse_model_profiles,
    recommend_model,
)

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 600
CHARS_PER_TOKEN = 3.0  # conservative for source code and French prose


class OllamaError(RuntimeError):
    """A concise, user-facing Ollama failure."""


def is_loopback_url(url: str) -> bool:
    """Only loopback is accepted: migration sources must stay on this host."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def extract_json_response(text: str) -> dict[str, Any]:
    """Parse the JSON object of a model answer (fences and prose tolerated)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        snippet = cleaned[start:end + 1]
        for candidate in (snippet, re.sub(r",\s*([}\]])", r"\1", snippet)):
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
    raise OllamaError("Le modèle n'a pas produit le JSON structuré demandé.")


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


@dataclass
class CallMetrics:
    purpose: str
    model: str
    prompt_chars: int
    num_ctx: int
    wall_seconds: float = 0.0
    load_seconds: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0
    done_reason: str = ""
    error: str = ""


@dataclass
class ProviderStats:
    calls: list[CallMetrics] = field(default_factory=list)

    @property
    def total_seconds(self) -> float:
        return round(sum(c.wall_seconds for c in self.calls), 2)


@functools.lru_cache(maxsize=1)
def cached_hardware() -> SystemHardware:
    """Hardware probing spawns processes on Windows: once per run is enough."""
    return detect_hardware()


class BaseLLMProvider(abc.ABC):
    """Abstract interface for local language model providers."""

    stats: ProviderStats

    @abc.abstractmethod
    def list_models(self) -> list[ModelProfile]:
        """List locally available models."""

    @abc.abstractmethod
    def choose_model(self, requested: str = "") -> str:
        """Select a suitable model name based on user request or hardware fit."""

    @abc.abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str = "",
        schema: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        purpose: str = "chat",
        num_predict: int = 1024,
    ) -> dict[str, Any]:
        """Send chat messages and return the parsed JSON object of the answer."""

    def context_budget(self, model: str = "", num_predict: int = 1024) -> int:
        """Characters of prompt that fit the context the call will request."""
        return int((self.max_context(model) - num_predict - 256) * CHARS_PER_TOKEN)

    def max_context(self, model: str = "") -> int:
        return 8192


def select_installed_model(requested: str, models: list[ModelProfile]) -> str:
    """Exact installed name for a request; a tag is never silently substituted.

    ``qwen2.5-coder:14b`` must be installed as such. ``qwen2.5-coder`` (no tag)
    means ``qwen2.5-coder:latest`` or, failing that, the only installed tag.
    """
    names = [m.name for m in models]
    if requested in names:
        return requested
    if ":" not in requested:
        if f"{requested}:latest" in names:
            return f"{requested}:latest"
        tagged = [n for n in names if n.split(":", 1)[0] == requested]
        if len(tagged) == 1:
            return tagged[0]
        if tagged:
            raise OllamaError(
                f"Plusieurs variantes de {requested!r} sont installées ({', '.join(tagged)}) : "
                "précisez le tag avec --ollama-model."
            )
    available = ", ".join(names) or "aucun"
    raise OllamaError(
        f"Le modèle {requested!r} n'est pas installé (disponibles : {available}). "
        f"Exécutez `ollama pull {requested}` ou choisissez un modèle installé."
    )


class OllamaProvider(BaseLLMProvider):
    """Concrete provider for local Ollama instances."""

    def __init__(self, url: str = DEFAULT_URL, model: str = "", timeout: int = DEFAULT_TIMEOUT):
        if not is_loopback_url(url):
            raise OllamaError(
                "Seule une URL Ollama locale (localhost/127.0.0.1/::1) est acceptée "
                "afin de ne pas exposer le code source."
            )
        self.url = url.rstrip("/")
        self.configured_model = model
        self.timeout = timeout
        self.stats = ProviderStats()
        self._models: list[ModelProfile] | None = None
        self._chosen: dict[str, str] = {}

    def _request(self, path: str, payload: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
        target = self.url + path
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            target,
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=max(1.0, timeout)) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise OllamaError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OllamaError(
                f"Ollama inaccessible sur {self.url} ou délai dépassé ({exc}). Lancez `ollama serve`."
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaError("Réponse Ollama invalide (JSON attendu).") from exc

    def list_models(self) -> list[ModelProfile]:
        if self._models is None:
            raw = self._request("/api/tags", timeout=10)
            self._models = parse_model_profiles(raw.get("models", []) if isinstance(raw, dict) else [])
        return self._models

    def choose_model(self, requested: str = "") -> str:
        target_name = requested or self.configured_model
        if target_name in self._chosen:
            return self._chosen[target_name]
        models = self.list_models()
        if target_name:
            chosen = select_installed_model(target_name, models)
        elif not models:
            raise OllamaError(
                "Aucun modèle Ollama installé. Installez-en un adapté au code, par exemple "
                "`ollama pull qwen2.5-coder:7b`, ou choisissez-le avec --ollama-model."
            )
        else:
            chosen = recommend_model(cached_hardware(), models)[0]
        self._chosen[target_name] = chosen
        return chosen

    def max_context(self, model: str = "") -> int:
        name = model or self.choose_model()
        profile = next((m for m in self.list_models() if m.name == name), None)
        model_context = profile.context_length if profile and profile.context_length else 4096
        return max(2048, min(model_context, context_cap(cached_hardware())))

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str = "",
        schema: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        purpose: str = "chat",
        num_predict: int = 1024,
    ) -> dict[str, Any]:
        selected = model or self.choose_model()
        prompt_chars = sum(len(m.get("content", "")) for m in messages)
        needed = estimate_tokens("".join(m.get("content", "") for m in messages)) + num_predict + 256
        limit = self.max_context(selected)
        if needed > limit:
            raise OllamaError(
                f"Invite trop longue pour le contexte disponible ({needed} > {limit} jetons) : "
                "réduisez --ollama-max-context."
            )
        num_ctx = 2048
        while num_ctx < needed:
            num_ctx *= 2
        num_ctx = min(num_ctx, limit)
        payload: dict[str, Any] = {
            "model": selected,
            "messages": messages,
            "stream": False,
            "keep_alive": "10m",
            "options": {"temperature": 0.1, "num_ctx": num_ctx, "num_predict": num_predict, **(options or {})},
        }
        if schema:
            payload["format"] = schema
        metrics = CallMetrics(purpose, selected, prompt_chars, num_ctx)
        self.stats.calls.append(metrics)
        started = time.monotonic()
        try:
            resp = self._request("/api/chat", payload=payload, timeout=timeout)
        except OllamaError as exc:
            metrics.error = str(exc)
            raise
        finally:
            metrics.wall_seconds = round(time.monotonic() - started, 2)
        if not isinstance(resp, dict):
            metrics.error = "réponse non JSON"
            raise OllamaError("Réponse Ollama invalide (objet JSON attendu).")
        metrics.load_seconds = round((resp.get("load_duration") or 0) / 1e9, 2)
        metrics.prompt_tokens = int(resp.get("prompt_eval_count") or 0)
        metrics.output_tokens = int(resp.get("eval_count") or 0)
        metrics.done_reason = str(resp.get("done_reason") or "")
        content = (resp.get("message") or {}).get("content", "")
        if not content or not content.strip():
            metrics.error = "réponse vide"
            raise OllamaError("Ollama n'a renvoyé aucun contenu.")
        if metrics.done_reason == "length":
            metrics.error = "réponse tronquée"
            raise OllamaError("Réponse tronquée par la limite de génération : JSON incomplet ignoré.")
        try:
            return extract_json_response(content)
        except OllamaError as exc:
            metrics.error = str(exc)
            raise


def configured_model(cli_model: str = "") -> str:
    """Return model configured by CLI or environment."""
    return cli_model or os.environ.get("ODOO_MIGRATOR_OLLAMA_MODEL", "")
