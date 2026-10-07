"""Conservative, model-aware checks of Python code against indexed addons."""

import ast
from pathlib import Path
import re

from lxml import etree

from . import fields, models


class Uses(ast.NodeVisitor):
    """Track recordset aliases and relational paths within a method."""

    def __init__(self, index):
        self.index = index
        self.aliases = {}
        self.usages = []
        self.model_uses = []

    def receiver(self, node):
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id)
        model = fields._env_model(node)
        if model:
            return model
        if isinstance(node, ast.Attribute):
            model = self.receiver(node.value)
            candidates = (
                set().union(
                    *(
                        self.index.comodels.get((m, node.attr), set())
                        for m in self.index.ancestors(model)
                    )
                )
                if model
                else set()
            )
            if len(candidates) == 1:
                return next(iter(candidates))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr
            in {
                "sudo",
                "with_context",
                "with_company",
                "with_user",
                "filtered",
                "sorted",
                "browse",
                "search",
                "create",
                "ensure_one",
                "exists",
            }
        ):
            return self.receiver(node.func.value)
        if isinstance(node, ast.Subscript):
            return self.receiver(node.value)

    def visit_ClassDef(self, node):
        saved = self.aliases
        names = fields._class_models(node)
        self.aliases = {"self": names[0]} if names else {}
        self.generic_visit(node)
        self.aliases = saved

    def visit_FunctionDef(self, node):
        saved = self.aliases.copy()
        self.generic_visit(node)
        self.aliases = saved

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node):
        self.visit(node.value)
        model = self.receiver(node.value)
        for target in node.targets:
            self.visit(target)
            if isinstance(target, ast.Name):
                self.aliases.pop(target.id, None)
                if model:
                    self.aliases[target.id] = model

    def visit_For(self, node):
        self.visit(node.iter)
        saved = self.aliases.copy()
        if isinstance(node.target, ast.Name):
            self.aliases.pop(node.target.id, None)
            model = self.receiver(node.iter)
            if model:
                self.aliases[node.target.id] = model
        for stmt in node.body + node.orelse:
            self.visit(stmt)
        self.aliases = saved

    def visit_Attribute(self, node):
        model = self.receiver(node.value)
        if model:
            self.usages.append((node, model, node.attr))
        self.generic_visit(node)

    def visit_Subscript(self, node):
        model = fields._env_model(node)
        if model:
            self.model_uses.append((node, model))
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute):
            model = self.receiver(node.func.value)
            if model and node.func.attr in {"write", "create", "update"} and node.args:
                arg = node.args[0]
                dictionaries = (
                    arg.elts if isinstance(arg, (ast.List, ast.Tuple)) else [arg]
                )
                for values in dictionaries:
                    if isinstance(values, ast.Dict):
                        for key in values.keys:
                            if isinstance(key, ast.Constant) and isinstance(
                                key.value, str
                            ):
                                self.usages.append((key, model, key.value))
        self.generic_visit(node)


def dependency_message(index, module, what, owners):
    owners = sorted(owners)
    circular = [owner for owner in owners if module in index.closure(owner)]
    if len(circular) == len(owners):
        return f"{what}: circular dependency; move this code into {', '.join(circular)} (field/model provider) or a bridge module"
    return f"{what}: add a provider to 'depends': {', '.join(o for o in owners if o not in circular)}"


def check_module(module, index, target_version=20, precision_names=None):
    module = Path(module)
    closure = index.closure(module.name)
    complete = not index.unknown_dependencies(module.name)
    for path in models._python_files(module):
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, ValueError):
            continue
        visitor = Uses(index)
        visitor.visit(tree)
        if precision_names:
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.keyword)
                    and node.arg == "digits"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                    and node.value.value not in precision_names
                ):
                    yield (
                        path,
                        node.value.lineno,
                        "error" if complete else "warning",
                        f"Unknown target decimal precision {node.value.value!r}; Odoo silently falls back to its default precision",
                    )
        seen = set()
        for node, model in visitor.model_uses:
            owners = set(index.owners(model))
            if owners and not owners & closure:
                yield (
                    path,
                    node.lineno,
                    "error" if complete else "warning",
                    dependency_message(index, module.name, f"Model {model}", owners),
                )
            elif not owners and complete and index.models.get("base"):
                yield (
                    path,
                    node.lineno,
                    "error",
                    f"Model {model} used through env[] is not defined in the indexed target",
                )
        for node, model, field in visitor.usages:
            key = (node.lineno, model, field)
            if key in seen:
                continue
            seen.add(key)
            ancestors = index.ancestors(model)
            owners = set().union(
                *(index.field_owners.get((m, field), set()) for m in ancestors)
            )
            if owners and not owners & closure:
                yield (
                    path,
                    node.lineno,
                    "error" if complete else "warning",
                    dependency_message(
                        index, module.name, f"Field {model}.{field}", owners
                    ),
                )
            if target_version >= 19 and model == "uom.uom" and field == "category_id":
                yield (
                    path,
                    node.lineno,
                    "error",
                    "uom.uom.category_id removed in Odoo 19; compare units with _has_common_reference(other_uom) (addons/uom/models/uom_uom.py)",
                )
            if (
                target_version >= 20
                and field == "sale_delay"
                and model in {"product.product", "product.template"}
            ):
                receiver = node.value if isinstance(node, ast.Attribute) else None
                explicit_company = receiver is not None and any(
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "with_company"
                    for n in ast.walk(receiver)
                )
                if not explicit_company:
                    yield (
                        path,
                        node.lineno,
                        "warning",
                        "Product sale_delay is now company_dependent and Integer: review with_company(record.company_id) when computing delays per line (Odoo 20 addons/sale/models/product_template.py)",
                    )
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            names = fields._class_models(cls)
            if not names:
                continue
            model = names[0]
            ancestors = index.ancestors(model)
            methods = set().union(*(index.methods.get(m, set()) for m in ancestors))
            for stmt in cls.body:
                call = getattr(stmt, "value", None)
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "fields"
                ):
                    for kw in call.keywords:
                        if (
                            kw.arg in {"compute", "inverse", "search"}
                            and isinstance(kw.value, ast.Constant)
                            and isinstance(kw.value.value, str)
                        ):
                            if (
                                kw.value.value not in methods
                                and complete
                                and ancestors <= index.defined
                            ):
                                yield (
                                    path,
                                    kw.value.lineno,
                                    "error",
                                    f"{model}: {kw.arg}={kw.value.value!r} names a method absent from the model and its indexed parents",
                                )
                if isinstance(
                    stmt, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and stmt.name.startswith(("_search_", "_compute_")):
                    owners = set().union(
                        *(
                            index.method_owners.get((m, stmt.name), set())
                            for m in ancestors
                        )
                    ) - {module.name}
                    has_super = any(
                        isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Name)
                        and n.func.id == "super"
                        for n in ast.walk(stmt)
                    )
                    field = stmt.name.split("_", 2)[-1]
                    mentions = any(
                        isinstance(n, ast.Attribute)
                        and n.attr == field
                        or isinstance(n, ast.Constant)
                        and n.value == field
                        for n in ast.walk(stmt)
                    )
                    if owners & closure and not has_super and not mentions:
                        yield (
                            path,
                            stmt.lineno,
                            "warning",
                            f"Possible accidental override of {model}.{stmt.name} from {', '.join(sorted(owners))}: no super() call or reference to {field}; review manually",
                        )
    yield from _check_action_methods(module, index, closure, complete)


def _model_from_xmlid(reference, index):
    """Resolve the conventional ``module.model_model_name`` external id."""
    local = reference.partition(".")[2]
    candidates = [
        model for model in index.defined if "model_" + model.replace(".", "_") == local
    ]
    return candidates[0] if len(candidates) == 1 else None


def _check_action_methods(module, index, closure, complete):
    """Check direct ``model.method()`` calls in cron/server action code."""
    for path in module.rglob("*.xml"):
        try:
            root = etree.parse(str(path)).getroot()
        except (OSError, etree.XMLSyntaxError):
            continue
        for record in root.xpath(
            ".//record[@model='ir.cron' or @model='ir.actions.server']"
        ):
            model_field = record.find("field[@name='model_id']")
            code_field = record.find("field[@name='code']")
            if model_field is None or code_field is None:
                continue
            model = _model_from_xmlid(model_field.get("ref", ""), index)
            code = "".join(code_field.itertext())
            if not model or not code:
                continue
            ancestors = index.ancestors(model)
            for match in re.finditer(r"\bmodel\.([A-Za-z_]\w*)\s*\(", code):
                method = match.group(1)
                owners = set().union(
                    *(
                        index.method_owners.get((parent, method), set())
                        for parent in ancestors
                    )
                )
                if owners & closure:
                    continue
                line = code_field.sourceline + code.count("\n", 0, match.start())
                if owners:
                    message = (
                        f"Scheduled/server action calls {model}.{method}(), provided only by "
                        f"{', '.join(sorted(owners))} outside this module's dependencies"
                    )
                elif complete and ancestors <= index.defined:
                    message = (
                        f"Scheduled/server action calls {model}.{method}(), but that method is "
                        "absent from the module and its indexed dependencies"
                    )
                else:
                    message = (
                        f"[incomplete] Scheduled/server action calls {model}.{method}(); the method "
                        "was not found in the available dependencies"
                    )
                yield path, line, "warning", message
