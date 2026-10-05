# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Migrating an already migrated module must not change anything."""

import shutil

import pytest

from odoo_module_migrate.__main__ import main

CASES = [
    ("module_080", "8.0", "13.0"),
    ("module_120", "12.0", "13.0"),
    ("module_130", "13.0", "14.0"),
    ("module_150", "15.0", "16.0"),
    ("module_160", "16.0", "17.0"),
    ("module_170", "17.0", "18.0"),
    ("module_180", "18.0", "19.0"),
]


def _snapshot(root):
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


def _migrate(directory, module, init, target):
    main([
        "--directory", str(directory), "--modules", module,
        "--init-version-name", init, "--target-version-name", target,
        "--no-commit", "--no-pre-commit", "--log-level", "ERROR",
    ])


@pytest.mark.parametrize("module,init,target", CASES)
def test_second_run_changes_nothing(tmp_path, module, init, target):
    shutil.copytree(f"tests/data_template/{module}", tmp_path / module)
    _migrate(tmp_path, module, init, target)
    first = _snapshot(tmp_path / module)
    _migrate(tmp_path, module, init, target)
    second = _snapshot(tmp_path / module)
    changed = sorted(k for k in first.keys() | second.keys() if first.get(k) != second.get(k))
    assert not changed, f"Non idempotent on: {changed}"
