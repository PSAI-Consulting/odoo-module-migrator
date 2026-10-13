# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Intelligence and local LLM review package for odoo-module-migrator."""

from .applicators import (
    ApplicatorResult,
    ExactTextApplicator,
    ManifestDependencyApplicator,
    PythonDictKeyApplicator,
    PythonImportApplicator,
    XmlAttributeApplicator,
    XmlXPathApplicator,
    apply_typed_operation,
    validate_syntax,
)
from .bench_verifier import BenchVerifier
from .confidence import ConfidenceReport, evaluate_confidence
from .provider import (
    BaseLLMProvider,
    OllamaError,
    OllamaProvider,
    configured_model,
    extract_json_response,
    is_loopback_url,
)
from .rag import HybridRAG, RAGChunk
from .repair import AutonomousRepairLoop, RepairAttempt, RepairSession
from .system_profile import (
    ModelProfile,
    SystemHardware,
    detect_hardware,
    get_ollama_info_text,
    recommend_model,
)

__all__ = [
    "ApplicatorResult",
    "AutonomousRepairLoop",
    "BaseLLMProvider",
    "BenchVerifier",
    "ConfidenceReport",
    "ExactTextApplicator",
    "HybridRAG",
    "ManifestDependencyApplicator",
    "ModelProfile",
    "OllamaError",
    "OllamaProvider",
    "PythonDictKeyApplicator",
    "PythonImportApplicator",
    "RAGChunk",
    "RepairAttempt",
    "RepairSession",
    "SystemHardware",
    "XmlAttributeApplicator",
    "XmlXPathApplicator",
    "apply_typed_operation",
    "configured_model",
    "detect_hardware",
    "evaluate_confidence",
    "extract_json_response",
    "get_ollama_info_text",
    "is_loopback_url",
    "recommend_model",
    "validate_syntax",
]
