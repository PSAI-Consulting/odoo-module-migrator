#!/usr/bin/env python3
"""Inventory changed signatures of commonly overridden Odoo model methods."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import yaml

PREFIXES = (
    "_prepare_", "_compute_", "_get_", "action_", "_action_", "_create_", "_post", "button_",
)


def literal_names(node: ast.AST) -> list[str]:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    names = [arg.arg for arg in args.posonlyargs]
    if args.posonlyargs:
        names.append("/")
    names += [arg.arg for arg in args.args]
    defaults = len(args.defaults)
    if defaults:
        for index in range(len(names) - defaults, len(names)):
            if names[index] not in {"/", "*"}:
                names[index] += "=?"
    if args.vararg:
        names.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        names.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        names.append(arg.arg + ("=?" if default is not None else ""))
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return f"{node.name}({', '.join(names)})"


def inventory(version: str):
    result = defaultdict(list)
    roots = [
        ("odoo", Path(rf"D:\Odoo\odoo\{version}\addons")),
        ("enterprise", Path(rf"D:\Odoo\enterprise\{version}")),
    ]
    for repository, root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "tests" in path.parts or "migrations" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError, ValueError):
                continue
            for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
                models = []
                for item in cls.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and target.id in {"_name", "_inherit"}:
                                models += literal_names(item.value)
                if not models:
                    continue
                for item in cls.body:
                    if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if not item.name.startswith(PREFIXES):
                        continue
                    rel = path.relative_to(root).as_posix()
                    for model in models:
                        result[(model, item.name)].append({
                            "signature": signature(item),
                            "repository": repository,
                            "file": rel,
                            "line": item.lineno,
                        })
    return result


def main() -> int:
    output = []
    cache = {}
    for old, new in (("16.0", "17.0"), ("17.0", "18.0"), ("18.0", "19.0"), ("19.0", "20.0")):
        before = cache.setdefault(old, inventory(old))
        after = cache.setdefault(new, inventory(new))
        for key in sorted(set(before) & set(after)):
            old_signatures = sorted({row["signature"] for row in before[key]})
            new_signatures = sorted({row["signature"] for row in after[key]})
            if old_signatures == new_signatures:
                continue
            output.append({
                "step": f"{old} -> {new}",
                "model": key[0],
                "method": key[1],
                "before": before[key],
                "after": after[key],
            })
    target = Path("lotb-method-signatures-lot-c.yaml")
    target.write_text(yaml.safe_dump(output, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")
    print(f"changed_signatures={len(output)} output={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
