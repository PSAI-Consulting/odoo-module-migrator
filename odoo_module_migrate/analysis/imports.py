# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Check the names imported from the Odoo addons against the target Odoo.

``from odoo.addons.stock.models.product import OPERATORS`` makes the module
fail at import time when the name was removed from the target file
(``OPERATORS`` of stock/models/product.py, removed in 19.0 by odoo
92301a5b300d). Only the addons of the target Odoo are checked, and a name is
reported only when the target file is parsed and defines it nowhere at the top
level (no star import, no module ``__getattr__``): no false positive.
"""

import ast
import pathlib

from .models import _python_files


def _module_dirs(paths):
    result = {}
    for base in paths:
        base = pathlib.Path(base)
        if base.is_dir():
            for manifest in base.glob("*/__manifest__.py"):
                result.setdefault(manifest.parent.name, manifest.parent)
    return result


def _top_level_names(tree):
    """Names defined at the top level of a module; None when unknown."""
    names = set()

    def visit(body):
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if stmt.name == "__getattr__":
                    return False
                names.add(stmt.name)
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                for alias in stmt.names:
                    if alias.name == "*":
                        return False
                    names.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for target in targets:
                    for node in ast.walk(target):
                        if isinstance(node, ast.Name):
                            names.add(node.id)
            elif isinstance(stmt, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                # conditional definitions count (over-approximation)
                bodies = [getattr(stmt, "body", []), getattr(stmt, "orelse", []),
                          getattr(stmt, "finalbody", [])]
                bodies += [h.body for h in getattr(stmt, "handlers", [])]
                for sub in bodies:
                    if visit(sub) is False:
                        return False
        return True

    return names if visit(tree.body) is not False else None


class ImportIndex:
    def __init__(self, reference_paths):
        self.modules = _module_dirs(reference_paths)
        self._cache = {}

    def names(self, module, parts):
        """Top-level names of odoo.addons.<module>.<parts>, None if unknown,
        False if the file does not exist."""
        key = (module, tuple(parts))
        if key not in self._cache:
            path = self.modules[module].joinpath(*parts)
            if path.with_suffix(".py").is_file():
                file = path.with_suffix(".py")
            elif (path / "__init__.py").is_file():
                file = path / "__init__.py"
            else:
                self._cache[key] = False
                return False
            try:
                result = _top_level_names(ast.parse(file.read_bytes()))
            except (SyntaxError, ValueError):
                result = None
            if result is not None and file.name == "__init__.py":
                # submodules can be imported from a package
                result |= {p.stem for p in file.parent.iterdir()
                           if p.suffix == ".py" or (p / "__init__.py").is_file()}
            self._cache[key] = result
        return self._cache[key]


def check_module(module, index):
    """Yield (path, line, message) for the names imported from an addon of
    the target Odoo that do not exist there anymore."""
    module = pathlib.Path(module)
    # not the tests: they are not loaded at installation
    for path in _python_files(module):
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module):
                continue
            parts = node.module.split(".")
            if parts[:2] != ["odoo", "addons"] or len(parts) < 3 or parts[2] not in index.modules:
                continue
            if parts[2] == module.name:
                continue
            names = index.names(parts[2], parts[3:])
            if names is None:
                continue
            if names is False:
                yield path, node.lineno, (
                    f"[import] {node.module} does not exist in the target Odoo:"
                    f" the module will not load"
                )
                continue
            for alias in node.names:
                if alias.name != "*" and alias.name not in names:
                    yield path, node.lineno, (
                        f"[import] '{alias.name}' is not defined in {node.module} in the target"
                        f" Odoo: the module will not load"
                    )
