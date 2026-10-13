# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Model-independent provider abstraction for local LLMs.

Enforces loopback-only safety, robust JSON parsing, model discovery,
and health checking while decoupling business logic from any specific LLM vendor.
"""

from __future__ import annotations

import abc
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .system_profile import (
    ModelProfile,
    detect_hardware,
    parse_model_profiles,
    query_ollama_tags,
    recommend_model,
)

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 600


class OllamaError(RuntimeError):
    """A concise, user-facing Ollama failure."""


def is_loopback_url(url: str) -> bool:
    """Only loopback is accepted: migration sources must stay on this host."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def extract_json_response(text: str) -> dict[str, Any]:
    """Robustly parse structured JSON from LLM text output.

    Handles markdown fences, preamble/postamble commentary, and common
    formatting artifacts without crashing.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()

    # Direct parse attempt
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Find outermost curly braces
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        snippet = cleaned[start:end + 1]
        try:
            data = json.loads(snippet)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            # Try minor repairs like trailing commas
            repaired = re.sub(r",\s*([}\]])", r"\1", snippet)
            try:
                data = json.loads(repaired)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

    raise OllamaError("Le modèle n'a pas produit le JSON structuré demandé.")


class BaseLLMProvider(abc.ABC):
    """Abstract interface for local language model providers."""

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
        schema: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """Send chat messages and return parsed structured response dict."""


class OllamaProvider(BaseLLMProvider):
    """Concrete provider for local Ollama instances."""

    def __init__(self, url: str = DEFAULT_URL, model: str = ""):
        if not is_loopback_url(url):
            raise OllamaError(
                "Seule une URL Ollama locale (localhost/127.0.0.1/::1) est acceptée "
                "afin de ne pas exposer le code source."
            )
        self.url = url.rstrip("/")
        self.configured_model = model

    def _request(self, path: str, payload: dict[str, Any] | None = None, timeout: int = DEFAULT_TIMEOUT) -> Any:
        target = self.url + path
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            target,
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise OllamaError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OllamaError(
                f"Ollama inaccessible sur {self.url} ({exc}). Lancez `ollama serve`."
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaError("Réponse Ollama invalide (JSON attendu).") from exc

    def list_models(self) -> list[ModelProfile]:
        raw = self._request("/api/tags", timeout=10).get("models", [])
        return parse_model_profiles(raw)

    def choose_model(self, requested: str = "") -> str:
        target_name = requested or self.configured_model
        models = self.list_models()
        model_names = [m.name for m in models]

        if target_name:
            target_base = target_name.split(":", 1)[0]
            for m in model_names:
                if m == target_name:
                    return m
            for m in model_names:
                if m.split(":", 1)[0] == target_base:
                    return m
            available = ", ".join(model_names) or "aucun"
            raise OllamaError(
                f"Le modèle {target_name!r} n'est pas installé (disponibles : {available}). "
                f"Exécutez `ollama pull {target_name}`."
            )

        if not models:
            raise OllamaError(
                "Aucun modèle Ollama installé. Installez-en un, par exemple "
                "`ollama pull qwen2.5-coder:7b`."
            )

        # Automatic recommendation tailored to detected hardware
        hardware = detect_hardware()
        rec_name, _rec_ctx, _speed = recommend_model(hardware, models)
        return rec_name

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str = "",
        schema: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        selected = model or self.choose_model()
        payload: dict[str, Any] = {
            "model": selected,
            "messages": messages,
            "stream": False,
            "keep_alive": "10m",
            "options": options or {"temperature": 0.1, "num_ctx": 4096, "num_predict": 700},
        }
        if schema:
            payload["format"] = schema

        resp = self._request("/api/chat", payload=payload, timeout=timeout)
        content = resp.get("message", {}).get("content", "")
        if not content:
            raise OllamaError("Ollama n'a renvoyé aucun contenu.")
        return extract_json_response(content)


def configured_model(cli_model: str = "") -> str:
    """Return model configured by CLI or environment."""
    return cli_model or os.environ.get("ODOO_MIGRATOR_OLLAMA_MODEL", "")
