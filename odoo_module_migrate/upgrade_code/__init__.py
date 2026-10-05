# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Orchestration of Odoo's official ``odoo/upgrade_code`` scripts.

The scripts are run by the target Odoo Python (see runner.py), after the
migrator's own rules, on all the migrated modules at once.
"""

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

from ..exception import ConfigException
from ..log import logger

RUNNER = pathlib.Path(__file__).with_name("runner.py")


@dataclass
class UpgradeCodeOptions:
    odoo_root: pathlib.Path
    odoo_python: str
    addons_path: list = field(default_factory=list)  # reference addons
    context_path: list = field(default_factory=list)  # custom addons (deps)

    @classmethod
    def from_args(cls, odoo_root, odoo_python=None, addons_path=None, context_path=None):
        root = pathlib.Path(odoo_root).resolve()
        if not (root / "odoo" / "upgrade_code").is_dir():
            raise ConfigException(
                f"--odoo-root {root}: 'odoo/upgrade_code' not found (Odoo >= 18 needed)"
            )
        reference = [root / "addons", root / "odoo" / "addons"]
        if addons_path:
            reference += [pathlib.Path(p) for p in addons_path.split(",") if p]
        else:
            reference += _guess_sibling_repositories(root)
        python = odoo_python or _guess_python(root)
        return cls(
            odoo_root=root,
            odoo_python=python,
            addons_path=[p.resolve() for p in reference if p.is_dir()],
            context_path=[
                pathlib.Path(p).resolve() for p in (context_path or "").split(",") if p
            ],
        )

    def odoo_version(self):
        release = (self.odoo_root / "odoo" / "release.py").read_text(encoding="utf-8")
        match = re.search(r"version_info\s*=\s*\(\s*['\"]?(?:saas~)?(\d+)['\"]?\s*,\s*(\d+)", release)
        return f"{match.group(1)}.{match.group(2)}" if match else None


def _guess_sibling_repositories(odoo_root):
    """D:/Odoo/odoo/20.0 -> D:/Odoo/enterprise/20.0, D:/Odoo/design-themes/20.0"""
    result = []
    for repo in ("enterprise", "design-themes"):
        candidate = odoo_root.parent.parent / repo / odoo_root.name
        if candidate.is_dir():
            logger.info("upgrade_code: using %s", candidate)
            result.append(candidate)
    return result


def _guess_python(odoo_root):
    if sys.version_info >= (3, 12):
        return sys.executable
    for candidate in (
        odoo_root / "venv" / "Scripts" / "python.exe",
        odoo_root / "venv" / "bin" / "python",
        odoo_root / ".venv" / "Scripts" / "python.exe",
        odoo_root / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    raise ConfigException(
        "Odoo >= 20 needs Python >= 3.12: give the Odoo Python with --odoo-python"
    )


@dataclass
class UpgradeCodeResult:
    scripts: list
    updated: list
    deleted: list
    blocked: list
    missing_modules: list
    summary: list

    def for_module(self, module_path):
        module_path = pathlib.Path(module_path).resolve()

        def inside(paths):
            return [p for p in paths if pathlib.Path(p).resolve().is_relative_to(module_path)]

        return inside(self.updated), inside(self.deleted)


def run_upgrade_code(options, module_paths, from_version, to_version, dry_run=False):
    """Run the official scripts on `module_paths` and log what happened."""
    module_paths = [pathlib.Path(p).resolve() for p in module_paths]
    target_major = int(float(to_version))
    odoo_version = options.odoo_version()
    if odoo_version and int(float(odoo_version)) != target_major:
        logger.warning(
            "upgrade_code: --odoo-root is Odoo %s but the target is %s",
            odoo_version, to_version,
        )
    with tempfile.TemporaryDirectory(prefix="odoo-upgrade-code-") as tmp:
        output = pathlib.Path(tmp) / "report.json"
        args = [
            options.odoo_python, str(RUNNER),
            "--odoo-root", str(options.odoo_root),
            "--addons-path", ",".join(map(str, options.addons_path)),
            "--context-path", ",".join(map(str, options.context_path)),
            "--modules", ",".join(map(str, module_paths)),
            "--from", from_version,
            "--to", to_version,
            "--output", str(output),
        ]
        if target_major >= 20:
            args.append("--owl3")
        if dry_run:
            args.append("--dry-run")
        logger.info(
            "Running Odoo upgrade_code scripts %s -> %s on %d module(s)...",
            from_version, to_version, len(module_paths),
        )
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        process = subprocess.run(args, capture_output=True, env=env)
        if process.returncode != 0 or not output.exists():
            raise RuntimeError(
                "upgrade_code runner failed:\n"
                + process.stderr.decode("utf-8", errors="replace")[-4000:]
            )
        data = json.loads(output.read_text(encoding="utf-8"))

    result = UpgradeCodeResult(
        scripts=data["scripts"],
        updated=data["updated"],
        deleted=data["deleted"],
        blocked=data["blocked"],
        missing_modules=data.get("missing_modules", []),
        summary=data.get("summary", []),
    )
    _log_result(result)
    return result


def _log_result(result):
    for script in result.scripts:
        if script["error"]:
            logger.error(
                "[upgrade_code %s] script failed, it was skipped:\n%s",
                script["name"], script["error"].strip().splitlines()[-1],
            )
        for record in script["logs"]:
            if record["level"] in ("WARNING", "ERROR", "CRITICAL"):
                getattr(logger, record["level"].lower())(
                    "[upgrade_code %s] %s", script["name"], record["message"].strip()
                )
    for path in result.updated:
        logger.info("[upgrade_code] updated %s", path)
    for path in result.deleted:
        logger.info("[upgrade_code] deleted %s", path)
    blocked_modules = sorted({_module_of(p) for p in result.blocked})
    if blocked_modules:
        logger.warning(
            "[upgrade_code] these dependencies would also be rewritten (not done, "
            "they are not migrated in this run): %s",
            ", ".join(blocked_modules),
        )
    if result.missing_modules:
        logger.warning(
            "[upgrade_code] dependencies not found in Odoo %s addons: %s",
            "target", ", ".join(result.missing_modules),
        )


def _module_of(path):
    path = pathlib.Path(path)
    for parent in path.parents:
        if (parent / "__manifest__.py").exists():
            return parent.name
    return path.parent.name
