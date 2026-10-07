"""Build reproducible, offline Community bundles from clean Odoo checkouts.

Usage: python tools/vendor_upgrade_code.py --source /src/odoo/20.0 --version 20.0
Official scripts and reference files are copied byte for byte. Only package
entry points are supplied here to avoid booting an Odoo server.
"""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def build(source, version, destination):
    source, destination = Path(source), Path(destination)
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=normal"],
        text=True,
    )
    if dirty.strip():
        raise ValueError(
            "Build official bundles from a clean Community checkout so the recorded revision is reproducible"
        )
    files = {}
    for base in (source / "addons", source / "odoo/addons"):
        for module in sorted(base.iterdir()):
            if not module.is_dir() or not (module / "__manifest__.py").exists():
                continue
            if module.name.startswith("test_"):
                continue
            for path in sorted(module.rglob("*")):
                relative = path.relative_to(module)
                if not path.is_file() or path.suffix not in {".py", ".xml", ".csv"}:
                    continue
                if {"tests", "static", "__pycache__"}.intersection(relative.parts):
                    continue
                files[path.relative_to(source).as_posix()] = path.read_bytes()
    for relative in (
        "odoo/cli/upgrade_code.py",
        "odoo/release.py",
        "odoo/tools/parse_version.py",
        "LICENSE",
        "COPYRIGHT",
    ):
        path = source / relative
        if path.exists():
            files[relative] = path.read_bytes()
    for path in sorted((source / "odoo/upgrade_code").glob("*.py")):
        files[path.relative_to(source).as_posix()] = path.read_bytes()
    # The package entry points deliberately expose only the official utilities
    # needed by upgrade_code, not an ORM, registry, database or server.
    files["odoo/__init__.py"] = (
        b'"""Standalone namespace for the bundled official upgrade scripts."""\n'
    )
    files["odoo/cli/__init__.py"] = (
        b"# Official upgrade_code.py uses its standalone Command fallback.\n"
    )
    tools_init = "from .parse_version import parse_version\nconfig = {}\n"
    set_expression = source / "odoo/tools/set_expression.py"
    if set_expression.exists():
        files["odoo/tools/set_expression.py"] = set_expression.read_bytes()
        misc = (source / "odoo/tools/misc.py").read_text(encoding="utf-8")
        tree = ast.parse(misc)
        function = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "groupby"
        )
        groupby = ast.get_source_segment(misc, function)
        files["odoo/tools/_groupby.py"] = (
            "# Extracted unchanged from Odoo tools/misc.py; see bundled LICENSE.\n"
            "from __future__ import annotations\nfrom collections import defaultdict\n"
            "from collections.abc import Iterable, Callable\n" + groupby + "\n"
        ).encode()
        tools_init += "from .set_expression import SetDefinitions\nfrom ._groupby import groupby\n"
    files["odoo/tools/__init__.py"] = tools_init.encode()
    provenance = {
        "version": version,
        "repository": "https://github.com/odoo/odoo",
        "revision": revision,
        "files": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(files.items())
        },
        "adapted": [
            "odoo/__init__.py",
            "odoo/cli/__init__.py",
            "odoo/tools/__init__.py",
            "odoo/tools/_groupby.py",
        ],
    }
    files["PROVENANCE.json"] = json.dumps(provenance, indent=2).encode()
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"odoo-{version}.zip"
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as output:
        for name, data in sorted(files.items()):
            item = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o644 << 16
            output.writestr(item, data)
    metadata = {
        "version": version,
        "revision": revision,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "repository": provenance["repository"],
        "files": len(files),
    }
    archive.with_suffix(".json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"{archive}: {len(files)} files, {archive.stat().st_size / 1024**2:.1f} MiB",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--version", required=True, choices=["18.0", "19.0", "20.0"])
    parser.add_argument(
        "--output",
        default=str(
            Path(__file__).resolve().parents[1]
            / "odoo_module_migrate/upgrade_code/bundles"
        ),
    )
    args = parser.parse_args()
    build(args.source, args.version, args.output)
