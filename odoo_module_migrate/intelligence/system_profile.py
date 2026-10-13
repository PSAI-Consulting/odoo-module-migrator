# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Hardware and local LLM environment discovery and profiling.

Detects available memory, CPU, GPU/VRAM, discovers installed Ollama models,
and recommends model profiles and context budgets tailored to the machine
without external heavy dependencies.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

CODER_FAMILIES = (
    "qwen2.5-coder",
    "qwen3-coder",
    "qwen-coder",
    "deepseek-coder",
    "codellama",
    "starcoder",
    "codeqwen",
    "codestral",
)


@dataclass
class ModelProfile:
    name: str
    parameter_size: str = ""
    family: str = ""
    families: list[str] = field(default_factory=list)
    format: str = "gguf"
    context_length: int = 4096
    size_bytes: int = 0
    is_coder: bool = False
    is_installed: bool = True
    quantization: str = ""

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / (1024**3), 2) if self.size_bytes else 0.0

    @property
    def approx_params_b(self) -> float:
        """Billions of parameters ("7.6B", "500M"); 7.0 when unknown."""
        cleaned = self.parameter_size.upper().strip()
        factor = 0.001 if cleaned.endswith("M") else 1.0
        try:
            return float(cleaned.rstrip("BM").strip()) * factor
        except ValueError:
            return 7.0


@dataclass
class SystemHardware:
    total_ram_gb: float
    avail_ram_gb: float
    cpu_count: int
    cpu_arch: str
    gpu_name: str = ""
    vram_gb: float = 0.0
    has_dedicated_gpu: bool = False


def detect_hardware() -> SystemHardware:
    """Detect RAM, CPU, and GPU without third-party libraries."""
    total_ram = 16.0
    avail_ram = 8.0
    cpu_count = os.cpu_count() or 4
    cpu_arch = platform.machine() or "x86_64"

    # RAM detection
    if os.name == "nt":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_ram = round(stat.ullTotalPhys / (1024**3), 1)
                avail_ram = round(stat.ullAvailPhys / (1024**3), 1)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Windows RAM query error: %s", exc)
    elif os.path.exists("/proc/meminfo"):
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                content = f.read()
            for line in content.splitlines():
                if line.startswith("MemTotal:"):
                    total_ram = round(int(line.split()[1]) / (1024 * 1024), 1)
                elif line.startswith("MemAvailable:"):
                    avail_ram = round(int(line.split()[1]) / (1024 * 1024), 1)
        except OSError as exc:
            logger.debug("Linux meminfo read error: %s", exc)
    else:
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            total_ram = round((pages * page_size) / (1024**3), 1)
            avail_ram = round(total_ram * 0.5, 1)
        except (AttributeError, ValueError, OSError) as exc:
            logger.debug("POSIX sysconf RAM query error: %s", exc)

    # GPU detection
    gpu_name = ""
    vram_gb = 0.0
    has_dedicated = False

    # Check nvidia-smi first if available
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            proc = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3, check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                first_line = proc.stdout.strip().splitlines()[0]
                parts = [p.strip() for p in first_line.split(",")]
                gpu_name = parts[0]
                if len(parts) > 1 and parts[1].isdigit():
                    vram_gb = round(float(parts[1]) / 1024, 1)
                has_dedicated = True
        except (subprocess.SubprocessError, OSError) as exc:
            logger.debug("nvidia-smi query error: %s", exc)

    if not gpu_name and os.name == "nt":
        # Check Windows display adapters
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -Property Name, AdapterRAM | ConvertTo-Json"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                adapters = data if isinstance(data, list) else [data]
                for adapter in adapters:
                    name = adapter.get("Name", "")
                    raw_ram = adapter.get("AdapterRAM") or 0
                    if "DisplayLink" in name:
                        continue
                    if "NVIDIA" in name.upper() or "GEFORCE" in name.upper() or "RTX" in name.upper():
                        gpu_name = name
                        vram_gb = round(raw_ram / (1024**3), 1)
                        has_dedicated = True
                        break
                    if not gpu_name and name:
                        gpu_name = name
                        vram_gb = round(raw_ram / (1024**3), 1)
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
            logger.debug("Win32_VideoController query error: %s", exc)

    return SystemHardware(
        total_ram_gb=total_ram,
        avail_ram_gb=avail_ram,
        cpu_count=cpu_count,
        cpu_arch=cpu_arch,
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        has_dedicated_gpu=has_dedicated,
    )


def query_ollama_version(url: str = "http://127.0.0.1:11434", timeout: int = 2) -> str:
    """Fetch Ollama server version."""
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/version")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return str(data.get("version", ""))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.debug("Ollama version query error: %s", exc)
        return ""


def query_ollama_tags(url: str = "http://127.0.0.1:11434", timeout: int = 5) -> list[dict[str, Any]]:
    """Fetch Ollama model tag listing."""
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("models", [])
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.debug("Ollama tags query error: %s", exc)
        return []


def parse_model_profiles(raw_models: list[dict[str, Any]]) -> list[ModelProfile]:
    """Convert raw Ollama /api/tags items into structured ModelProfiles."""
    profiles = []
    for item in raw_models:
        name = item.get("name", "")
        if not name:
            continue
        details = item.get("details", {})
        families = details.get("families", [])
        family = details.get("family", "")
        if not families and family:
            families = [family]
        param_size = details.get("parameter_size", "")
        size_bytes = int(item.get("size", 0) or 0)
        context_len = int(details.get("context_length", 4096) or 4096)

        is_coder = any(fam in name.lower() for fam in CODER_FAMILIES) or any(
            any(c in f.lower() for c in ("code", "coder")) for f in families
        )
        profiles.append(
            ModelProfile(
                name=name,
                parameter_size=param_size,
                family=family,
                families=families,
                format=details.get("format", "gguf"),
                context_length=context_len,
                size_bytes=size_bytes,
                is_coder=is_coder,
                is_installed=True,
                quantization=details.get("quantization_level", ""),
            )
        )
    return profiles


def context_cap(hardware: SystemHardware) -> int:
    """Largest context the machine is assumed to afford with a quantized model."""
    if hardware.has_dedicated_gpu and hardware.vram_gb >= 20:
        return 32768
    if hardware.total_ram_gb > 40 or (hardware.has_dedicated_gpu and hardware.vram_gb >= 10):
        return 16384
    if hardware.total_ram_gb > 20:
        return 12288
    return 8192


def recommend_model(
    hardware: SystemHardware, installed_models: list[ModelProfile]
) -> tuple[str, int, str]:
    """Return (recommended_model_name, recommended_context, speed_estimate)."""
    ram = hardware.total_ram_gb
    has_gpu = hardware.has_dedicated_gpu

    # Context recommendation: the migrator sizes num_ctx from each prompt and
    # never exceeds this cap.
    rec_ctx = context_cap(hardware)

    # Speed estimation
    if has_gpu and hardware.vram_gb >= 6:
        speed_est = f"GPU accéléré ({hardware.gpu_name}, {hardware.vram_gb} Go VRAM) : rapide (~15 à 45s par module)."
    elif hardware.cpu_count >= 8:
        speed_est = f"CPU pur ({hardware.cpu_count} threads) : lent (plusieurs minutes par appel pour un 7B)."
    else:
        speed_est = f"CPU limité ({hardware.cpu_count} threads) : très lent ; réduire --ollama-max-context."

    # Any installed model may be chosen explicitly; the automatic choice only
    # prefers code models that fit in memory, larger being better.
    coder_models = [m for m in installed_models if m.is_coder]
    pool = coder_models if coder_models else installed_models

    if not pool:
        default_name = "qwen2.5-coder:7b" if ram <= 24 else ("qwen2.5-coder:14b" if ram <= 48 else "qwen2.5-coder:32b")
        return default_name, rec_ctx, speed_est

    memory_budget = max(hardware.vram_gb if has_gpu else 0.0, ram * 0.55)

    def score_fit(m: ModelProfile) -> float:
        size_gb = m.size_gb or m.approx_params_b * 0.6
        score = 10.0 if m.is_coder else 0.0
        if size_gb > memory_budget:
            return score - 100.0 - size_gb
        return score + 5.0 * size_gb / memory_budget

    best = max(pool, key=score_fit)
    return best.name, rec_ctx, speed_est


def get_ollama_info_text(url: str = "http://127.0.0.1:11434") -> str:
    """Generate the user-facing diagnostic text for --ollama-info."""
    hardware = detect_hardware()
    version = query_ollama_version(url)
    raw_models = query_ollama_tags(url)
    models = parse_model_profiles(raw_models)
    rec_model, rec_ctx, speed_est = recommend_model(hardware, models)

    lines = [
        "=== Diagnostic de l'environnement Ollama local ===",
        "",
        f"Serveur local : {url}",
        f"Version Ollama : {version or 'Inaccessible (lancez `ollama serve`)'}",
        "",
        "Matériel détecté :",
        f"  RAM totale       : {hardware.total_ram_gb:.1f} Go (disponible: {hardware.avail_ram_gb:.1f} Go)",
        f"  Processeur       : {hardware.cpu_count} threads logiques ({hardware.cpu_arch})",
    ]
    if hardware.gpu_name:
        gpu_line = f"  GPU              : {hardware.gpu_name}"
        if hardware.vram_gb:
            gpu_line += f" ({hardware.vram_gb:.1f} Go VRAM)"
        if hardware.has_dedicated_gpu:
            gpu_line += " [dédié]"
        else:
            gpu_line += " [intégré]"
        lines.append(gpu_line)
    else:
        lines.append("  GPU              : aucun GPU dédié détecté (inférence CPU)")

    lines += [
        "",
        f"Modèles installés ({len(models)}) :",
    ]
    if models:
        for m in models:
            coder_flag = " [Code]" if m.is_coder else ""
            lines.append(
                f"  - {m.name:<25} ({m.parameter_size or 'taille n/d'}, {m.quantization or 'quantif. n/d'}, "
                f"{m.size_gb} Go, contexte {m.context_length}){coder_flag}"
            )
    else:
        lines.append("  (aucun modèle installé - exécutez `ollama pull qwen2.5-coder:7b`)")

    lines += [
        "",
        "Recommandations automatiques :",
        f"  Modèle conseillé  : {rec_model}",
        f"  Contexte maximal  : {rec_ctx} jetons (num_ctx calculé pour chaque invite, jamais au-delà)",
        f"  Vitesse estimée   : {speed_est}",
        "",
        "Politique matérielle indicative :",
        "  - 16 Go RAM : modèle code 7B quantifié (Q4), contexte <= 8192",
        "  - 32 Go RAM : 14B code, ou 30B/32B quantifié si marge mémoire, contexte <= 12288",
        "  - 64 Go RAM ou GPU >= 20 Go : 30B/32B code, contexte <= 16384-32768",
        "  - Choix explicite toujours prioritaire avec `--ollama-model`.",
    ]
    return "\n".join(lines)
