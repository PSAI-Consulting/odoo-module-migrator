#!/usr/bin/env python3
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Static checks of migrated modules, before trying to install them.

    python tools/check_modules.py <modules_dir> --addons-path D:/Odoo/odoo/20.0/addons,...

Checks: Python files compile, XML files parse, the manifest is a literal dict,
each dependency exists (in <modules_dir> or the addons path), each 'data' /
'demo' file exists. Exit code 1 if a problem is found.
"""

import argparse
import ast
import pathlib
import sys

from lxml import etree


def module_names(paths):
    names = set()
    for path in paths:
        path = pathlib.Path(path)
        if path.is_dir():
            names.update(p.parent.name for p in path.glob("*/__manifest__.py"))
    return names


def check_module(module, available):
    problems = []
    manifest_path = module / "__manifest__.py"
    try:
        manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, SyntaxError) as e:
        return [f"__manifest__.py: not a literal dict ({e})"]
    for dep in manifest.get("depends", []):
        if dep not in available:
            problems.append(f"__manifest__.py: unknown dependency '{dep}'")
    for key in ("data", "demo"):
        for name in manifest.get(key, []):
            if not (module / name).exists():
                problems.append(f"__manifest__.py: {key} file not found '{name}'")
    for path in sorted(module.rglob("*.py")):
        try:
            compile(path.read_bytes(), str(path), "exec")
        except SyntaxError as e:
            problems.append(f"{path.relative_to(module)}:{e.lineno}: {e.msg}")
    for path in sorted(module.rglob("*.xml")):
        if "static" in path.relative_to(module).parts[:1] and "lib" in path.parts:
            continue
        try:
            etree.parse(str(path))
        except etree.XMLSyntaxError as e:
            problems.append(f"{path.relative_to(module)}:{e.lineno}: {e.msg}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory")
    parser.add_argument("--addons-path", default="", help="comma separated")
    parser.add_argument("--modules", default="", help="comma separated (default: all)")
    args = parser.parse_args(argv)

    directory = pathlib.Path(args.directory)
    available = module_names([directory, *args.addons_path.split(",")]) | {"base"}
    names = [m for m in args.modules.split(",") if m] or sorted(module_names([directory]))
    total = 0
    for name in names:
        problems = check_module(directory / name, available)
        total += len(problems)
        status = "OK" if not problems else f"{len(problems)} problem(s)"
        print(f"{name}: {status}")
        for problem in problems:
            print(f"    {problem}")
    print(f"\n{len(names)} module(s), {total} problem(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
