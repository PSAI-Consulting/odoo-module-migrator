# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Check that the models used by a module exist in the target Odoo.

A class inheriting a model that does not exist anymore (``_inherit`` /
``_inherits``), or a relational field whose comodel does not exist, prevents
the module from installing (e.g. ``barcodes.barcode_events_mixin`` or
``stock.valuation.layer`` in 20.0). The models available to a module are the
ones defined by the module and by its dependencies (``depends`` closure):
a model is reported only when it is defined nowhere there.
"""

import ast
import collections
import pathlib
import re

RELATIONAL = {"Many2one", "One2many", "Many2many", "Many2oneReference"}


def _str_values(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _python_files(module):
    for path in pathlib.Path(module).rglob("*.py"):
        parts = path.relative_to(module).parts
        if parts and parts[0] in ("tests", "static", "migrations", "upgrades"):
            continue
        yield path


NAME_RE = re.compile(r"""^\s{4}_name\s*=\s*['"]([\w.]+)['"]""", re.M)


def _classes(path):
    """(lineno, _name, _inherit list, _inherits keys, [(line, comodel)])."""
    try:
        tree = ast.parse(path.read_bytes())
    except (SyntaxError, ValueError):
        # newer Python syntax (Odoo 20 needs 3.12): the model names are enough
        text = path.read_bytes().decode("utf-8", "replace")
        for match in NAME_RE.finditer(text):
            yield text.count("\n", 0, match.start()) + 1, match.group(1), [], [], []
        return
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        name, inherit, inherits, comodels = None, [], [], []
        for stmt in cls.body:
            target = None
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                target = stmt.targets[0].id
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                target = stmt.target.id
            if target is None or stmt.value is None:
                continue
            if target == "_name":
                name = (_str_values(stmt.value) or [None])[0]
            elif target == "_inherit":
                inherit = _str_values(stmt.value)
            elif target == "_inherits" and isinstance(stmt.value, ast.Dict):
                inherits = [k.value for k in stmt.value.keys if isinstance(k, ast.Constant)]
            elif (
                isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Attribute)
                and stmt.value.func.attr in RELATIONAL
                and isinstance(stmt.value.func.value, ast.Name) and stmt.value.func.value.id == "fields"
            ):
                comodel = None
                if stmt.value.args and isinstance(stmt.value.args[0], ast.Constant):
                    comodel = stmt.value.args[0].value
                for kw in stmt.value.keywords:
                    if kw.arg == "comodel_name" and isinstance(kw.value, ast.Constant):
                        comodel = kw.value.value
                if isinstance(comodel, str) and "." in comodel:
                    comodel_line = stmt.lineno
                    comodels.append((comodel_line, comodel))
        if name or inherit:
            yield cls.lineno, name, inherit, inherits, comodels


class ModelIndex:
    def __init__(self):
        self.models = collections.defaultdict(set)  # module -> models it defines
        self.depends = {}

    def add_module(self, module):
        module = pathlib.Path(module)
        try:
            manifest = ast.literal_eval(
                (module / "__manifest__.py").read_text(encoding="utf-8", errors="replace").lstrip()
            )
        except (ValueError, SyntaxError):
            manifest = {}
        self.depends[module.name] = manifest.get("depends", [])
        for path in _python_files(module):
            for _line, name, inherit, _inherits, _comodels in _classes(path):
                # a model is defined by _name; _inherit with one name and no
                # _name extends it (it exists in a dependency)
                if name:
                    self.models[module.name].add(name)

    @classmethod
    def build(cls, paths):
        index = cls()
        for base in paths:
            base = pathlib.Path(base)
            if base.is_dir():
                for manifest in base.glob("*/__manifest__.py"):
                    index.add_module(manifest.parent)
        return index

    def unknown_dependencies(self, module):
        """Dependencies (direct or not) absent from the indexed addons paths."""
        result, todo, seen = [], [module, "base"], set()
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            if name not in self.depends:
                result.append(name)
            todo.extend(self.depends.get(name, ()))
        return sorted(result)

    def available(self, module):
        result, todo, seen = set(), [module, "base"], set()
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            result |= self.models.get(name, set())
            todo.extend(self.depends.get(name, ()))
        return result


def check_module(module, index):
    """Yield (path, line, message) for the models that do not exist."""
    module = pathlib.Path(module)
    available = index.available(module.name)
    if not index.models.get("base"):
        return  # no reference addons indexed: nothing can be checked
    if index.unknown_dependencies(module.name):
        return  # a dependency outside the addons paths may define any model
    for path in _python_files(module):
        for line, name, inherit, inherits, comodels in _classes(path):
            for parent in [*inherit, *inherits]:
                if parent != name and parent not in available:
                    yield path, line, (
                        f"[model] '{parent}' (inherited) does not exist in the target Odoo,"
                        f" nor in the dependencies of the module: the module will not install"
                    )
            for comodel_line, comodel in comodels:
                if comodel not in available:
                    yield path, comodel_line, (
                        f"[model] '{comodel}' (comodel of a relational field) does not exist"
                        f" in the target Odoo, nor in the dependencies of the module"
                    )
