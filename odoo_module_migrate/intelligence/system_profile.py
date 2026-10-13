# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Hardware and local LLM environment discovery and profiling.

Detects available memory, CPU, GPU/VRAM, discovers installed Ollama models,
and recommends model profiles and context budgets tailored to the machine
without external heavy dependencies.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

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

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / (1024**3), 2) if self.size_bytes else 0.0

    @property
    def approx_params_b(self) -> float:
        if not self.parameter_size:
            return 7.0
        cleaned = self.parameter_size.upper().replace("B", "").strip()
        try:
            return float(cleaned)
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
        except Exception:
            pass
    elif os.path.exists("/proc/meminfo"):
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                content = f.read()
            for line in content.splitlines():
                if line.startswith("MemTotal:"):
                    total_ram = round(int(line.split()[1]) / (1024 * 1024), 1)
                elif line.startswith("MemAvailable:"):
                    avail_ram = round(int(line.split()[1]) / (1024 * 1024), 1)
        except Exception:
            pass
    else:
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            total_ram = round((pages * page_size) / (1024**3), 1)
            avail_ram = round(total_ram * 0.5, 1)
        except Exception:
            pass

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
        except Exception:
            pass

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
        except Exception:
            pass

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
    except Exception:
        return ""


def query_ollama_tags(url: str = "http://127.0.0.1:11434", timeout: int = 5) -> list[dict[str, Any]]:
    """Fetch Ollama model tag listing."""
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("models", [])
    except Exception:
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
            )
        )
    return profiles


def recommend_model(
    hardware: SystemHardware, installed_models: list[ModelProfile]
) -> tuple[str, int, str]:
    """Return (recommended_model_name, recommended_context, speed_estimate)."""
    ram = hardware.total_ram_gb
    has_gpu = hardware.has_dedicated_gpu

    # Context recommendation
    if ram <= 16.5:
        rec_ctx = 4096
    elif ram <= 34.0:
        rec_ctx = 4096 if not has_gpu else 8192
    else:
        rec_ctx = 8192

    # Speed estimation
    if has_gpu and hardware.vram_gb >= 6:
        speed_est = f"GPU accéléré ({hardware.gpu_name}, {hardware.vram_gb} Go VRAM) : rapide (~15 à 45s par module)."
    elif hardware.cpu_count >= 8:
        speed_est = f"CPU pur ({hardware.cpu_count} cœurs) : modéré (~3 à 5 min par module pour 7B / 4096 tokens ; éviter 8192)."
    else:
        speed_est = f"CPU limité ({hardware.cpu_count} cœurs) : lent (~5 à 8 min par module ; restreindre le contexte)."

    # Model recommendation among installed
    coder_models = [m for m in installed_models if m.is_coder]
    pool = coder_models if coder_models else installed_models

    if not pool:
        default_name = "qwen2.5-coder:7b" if ram <= 24 else ("qwen2.5-coder:14b" if ram <= 48 else "qwen2.5-coder:32b")
        return default_name, rec_ctx, speed_est

    # Score models based on fit
    def score_fit(m: ModelProfile) -> float:
        params = m.approx_params_b
        score = 10.0 if m.is_coder else 2.0
        if "qwen2.5-coder" in m.name.lower():
            score += 5.0

        if ram <= 18:
            # Ideal is 7B
            diff = abs(params - 7.0)
            score -= diff * 3.0
            if params > 10.0:
                score -= 20.0
        elif ram <= 36:
            # Ideal is 14B or 7B
            diff = min(abs(params - 14.0), abs(params - 7.0))
            score -= diff * 2.0
            if params > 20.0:
                score -= 15.0
        else:
            # Ideal is 32B or 14B
            diff = min(abs(params - 32.0), abs(params - 14.0))
            score -= diff * 1.5

        return score

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
        f"  Processeur       : {hardware.cpu_count} cœurs ({hardware.cpu_arch})",
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
                f"  - {m.name:<25} ({m.parameter_size or 'taille n/d'}, {m.size_gb} Go disk){coder_flag}"
            )
    else:
        lines.append("  (aucun modèle installé - exécutez `ollama pull qwen2.5-coder:7b`)")

    lines += [
        "",
        "Recommandations automatiques :",
        f"  Modèle conseillé  : {rec_model}",
        f"  Contexte conseillé: {rec_ctx} tokens",
        f"  Vitesse estimée   : {speed_est}",
        "",
        "Politique matérielle indicative :",
        "  - 16 Go RAM : 7B code (qwen2.5-coder:7b), contexte 4096",
        "  - 32 Go RAM : 14B code, ou 30B/32B quantifié si marge mémoire, contexte 4096-8192",
        "  - 64 Go RAM : 30B/32B code, contexte 8192",
        "  - Choix explicite toujours prioritaire avec `--ollama-model`.",
    ]
    return "\n".join(lines)
