#!/usr/bin/env python3
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Canonical snapshot of the rules seen by every migration script.

The snapshot is what ``BaseMigrationScript.parse_rules()`` leaves on each
script (``_RENAMED_FIELDS``, ``_TEXT_REPLACES``... and the global functions),
plus the per-extension text rules that the scripts really apply
(``_file_rules``): order and priority included, since "first rule wins".

``tests/fixtures/rules_baseline.json`` keeps one digest per script and
attribute, captured with the historical loader (commit 19a5551) before the
structured rule layer existed; ``tests/test_rules_equivalence.py`` proves the
current loader still produces exactly the same data.

Usage::

    python tools/rules_baseline.py --check            # compare with the fixture
    python tools/rules_baseline.py --dump out.json    # full canonical data, to diff
    python tools/rules_baseline.py --write            # refresh the fixture (only
                                                      # after a reviewed rule change)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
import pathlib
import pkgutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "rules_baseline.json"

ATTRIBUTES = (
    "_DEPRECATED_MODULES", "_REMOVED_FIELDS", "_REMOVED_MODELS", "_RENAMED_FIELDS",
    "_RENAMED_METHODS", "_RENAMED_MODELS", "_FIELD_TYPES", "_FIELD_PROPERTIES",
    "_MENU_PARENT_HINTS", "_TEXT_REPLACES", "_TEXT_ERRORS", "_TEXT_WARNINGS",
    "_FILE_RENAMES", "_DROPPED_RECORD_FIELDS", "_GLOBAL_FUNCTIONS",
)


def canonical(value):
    """JSON-able value keeping the order of lists and dicts."""
    if inspect.isfunction(value):
        return f"<function {value.__module__}.{value.__qualname__}>"
    if isinstance(value, dict):
        return [["<dict>"]] + [[canonical(k), canonical(v)] for k, v in value.items()]
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def scripts():
    """{script module name: [script instances]} for every migration script."""
    sys.path.insert(0, str(ROOT))
    from odoo_module_migrate.base_migration_script import BaseMigrationScript

    package = importlib.import_module("odoo_module_migrate.migration_scripts")
    result = {}
    for _loader, name, _is_pkg in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
        if not name.startswith("migrate_"):
            continue
        module = importlib.import_module(f"{package.__name__}.{name}")
        instances = [
            cls() for _n, cls in inspect.getmembers(module, inspect.isclass)
            if cls is not BaseMigrationScript and issubclass(cls, BaseMigrationScript)
            and cls.__module__ == module.__name__
        ]
        for instance in instances:
            instance.parse_rules()
        result[name] = instances
    return result


def snapshot():
    """{script: {attribute: canonical data}}."""
    from odoo_module_migrate.config import _ALLOWED_EXTENSIONS

    data = {}
    for name, instances in scripts().items():
        for index, script in enumerate(instances):
            key = name if index == 0 else f"{name}#{index}"
            entry = {attr: canonical(getattr(script, attr)) for attr in ATTRIBUTES}
            for extension in _ALLOWED_EXTENSIONS:
                for kind, rules in script._file_rules(extension).items():
                    entry[f"file_rules{extension}:{kind}"] = canonical(rules)
            data[key] = entry
    data["<readers>"] = readers()
    return data


def readers():
    """Rules read outside the migration scripts (dependency aliases of
    upgrade_code, merged modules of earlier steps, text_errors patterns of the
    odoo.tools import checks)."""
    from odoo_module_migrate import migration_rules, odoo_tools_imports

    result = {}
    for start in range(8, 20):
        for end in range(start + 1, 21):
            aliases = migration_rules.module_aliases(f"{start}.0", f"{end}.0")
            result[f"upgrade_code_aliases:{start}->{end}"] = canonical(aliases)
    for end in range(9, 21):
        result[f"merged_modules_until:{end}"] = canonical(migration_rules.merged_module_rules(end * 10))
    steps = ROOT / "odoo_module_migrate" / "migration_scripts" / "text_errors"
    for step in sorted(p.name for p in steps.iterdir() if p.is_dir()):
        result[f"tools_import_error_patterns:{step}"] = canonical(
            odoo_tools_imports.load_error_patterns(str(steps / step))
        )
    return result


def digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def summary(data):
    return {
        script: {
            attr: {"count": len(value) - (1 if value and value[0] == ["<dict>"] else 0), "sha256": digest(value)}
            for attr, value in attrs.items()
        }
        for script, attrs in data.items()
    }


def differences(expected, actual):
    problems = []
    for script in sorted(set(expected) | set(actual)):
        if script not in actual or script not in expected:
            problems.append(f"{script}: script {'missing' if script not in actual else 'added'}")
            continue
        for attr in sorted(set(expected[script]) | set(actual[script])):
            if expected[script].get(attr) != actual[script].get(attr):
                problems.append(f"{script}.{attr}: {expected[script].get(attr)} != {actual[script].get(attr)}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dump")
    args = parser.parse_args(argv)
    data = snapshot()
    if args.dump:
        pathlib.Path(args.dump).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    current = summary(data)
    if args.write:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(current, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if args.check:
        problems = differences(json.loads(FIXTURE.read_text(encoding="utf-8")), current)
        for problem in problems:
            print(problem)
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
