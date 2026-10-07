"""Offline official scripts and Community references shipped in the wheel."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

from ..exception import ConfigException
from ..log import logger

BUNDLES = Path(__file__).with_name("bundles")


def materialize(version):
    archive = BUNDLES / f"odoo-{version}.zip"
    metadata_path = archive.with_suffix(".json")
    if not archive.is_file() or not metadata_path.is_file():
        raise ConfigException(
            f"No bundled official scripts for Odoo {version}; supply --odoo-root or use --no-upgrade-code"
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    root = (
        Path(
            os.environ.get(
                "LOCALAPPDATA",
                os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")),
            )
        )
        / "odoo-module-migrator"
        / "official"
    )
    destination = root / f"{version}-{metadata['sha256'][:16]}"
    marker = destination / ".ready"
    if marker.is_file() and marker.read_text() == metadata["sha256"]:
        return destination
    if hashlib.sha256(archive.read_bytes()).hexdigest() != metadata["sha256"]:
        raise ConfigException(
            f"Bundled Odoo {version} archive failed its integrity check; reinstall the package"
        )
    root.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Preparing bundled Odoo %s scripts and Community references (first run only)...",
        version,
    )
    with tempfile.TemporaryDirectory(prefix="extract-", dir=root) as tmp:
        staging = Path(tmp) / "sources"
        staging.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                path = (staging / item.filename).resolve()
                if not path.is_relative_to(
                    staging.resolve()
                ) or item.filename.startswith(("/", "\\")):
                    raise ConfigException("Unsafe path in bundled sources")
            bundle.extractall(staging)
        (staging / ".ready").write_text(metadata["sha256"])
        try:
            staging.rename(destination)
        except FileExistsError:
            if not marker.is_file() or marker.read_text() != metadata["sha256"]:
                raise ConfigException(
                    f"Incomplete bundle cache at {destination}; choose another cache directory"
                )
    return destination


def options(version, context_paths=(), addons_paths=()):
    from . import UpgradeCodeOptions

    if sys.version_info < (3, 12):
        raise ConfigException(
            "The all-in-one official scripts require Python 3.12+. Install the tool with Python 3.12, or use --no-upgrade-code for rules only."
        )
    root = materialize(version)
    logger.info("Using bundled official Odoo %s scripts (offline)", version)
    return UpgradeCodeOptions(
        root,
        sys.executable,
        [root / "addons", root / "odoo/addons", *map(Path, addons_paths)],
        list(dict.fromkeys(Path(p).resolve() for p in context_paths)),
    )
