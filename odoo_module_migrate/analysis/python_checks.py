"""Conservative, model-aware checks of Python code against indexed addons."""

import ast
import difflib
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
        self.called = set()

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
        if model and id(node) not in self.called:
            self.usages.append((node, model, node.attr))
        self.generic_visit(node)

    def visit_Subscript(self, node):
        model = fields._env_model(node)
        if model:
            self.model_uses.append((node, model))
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute):
            self.called.add(id(node.func))
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


def apply_field_renames(module, index, renames):
    """Apply field renames where the target index proves the receiver model.

    This late pass complements the standalone rule engine with relation aliases
    such as ``order -> order.order_line -> line``. It remains conservative:
    only attribute accesses with one resolved model are changed.
    """
    changed = []
    for path in models._python_files(Path(module)):
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        visitor = Uses(index)
        visitor.visit(tree)
        positions = fields._Positions(text)
        edits = set()
        for node, model, field in visitor.usages:
            replacement = renames.get((model, field))
            if not replacement or Path(module).name in index.field_owners.get(
                (model, field), set()
            ):
                continue
            end = positions.offset(node.end_lineno, node.end_col_offset)
            edits.add((end - len(field), end, replacement, model, field, node.lineno))
        if not edits:
            continue
        for start, end, replacement, _model, _field, _line in sorted(
            edits, reverse=True
        ):
            text = text[:start] + replacement + text[end:]
        path.write_text(text, encoding="utf-8")
        changed.extend(
            (path, line, model, field, replacement)
            for _start, _end, replacement, model, field, line in edits
        )
    return changed


def dependency_message(index, module, what, owners):
    owners = sorted(owners)
    circular = [owner for owner in owners if module in index.closure(owner)]
    if len(circular) == len(owners):
        return f"{what}: circular dependency; move this code into {', '.join(circular)} (field/model provider) or a bridge module"
    return f"{what}: add a provider to 'depends': {', '.join(o for o in owners if o not in circular)}"


def _seller_info_extracted(call, tree):
    """Whether an Odoo 20 _select_seller result is already unwrapped."""
    assigned = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and node.value is call
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name)
    }
    for node in ast.walk(tree):
        receiver = None
        key = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
        ):
            receiver, key = node.func.value, node.args[0]
        elif isinstance(node, ast.Subscript):
            receiver, key = node.value, node.slice
        if not isinstance(key, ast.Constant) or key.value != "supplierinfo":
            continue
        if receiver is call or (
            isinstance(receiver, ast.Name) and receiver.id in assigned
        ):
            return True
    return False


def _dynamic_record(node):
    """Whether an expression is a recordset from env[<dynamic model>]."""
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        node = node.func.value
    if not isinstance(node, ast.Subscript):
        return False
    value = node.value
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "env"
        and not (
            isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        )
    )


def _dynamic_model_issues(tree):
    """Attribute accesses on records whose model name is only known at runtime."""
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and _dynamic_record(node.value):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            aliases.update(target.id for target in targets if isinstance(target, ast.Name))
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr.startswith("_"):
            continue
        receiver_dynamic = (
            isinstance(node.value, ast.Name) and node.value.id in aliases
        ) or _dynamic_record(node.value)
        if not receiver_dynamic:
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Call) and parent.func is node:
            continue  # browse(), filtered()... are recordset methods, not fields
        augmented = isinstance(parent, ast.AugAssign) and parent.target is node
        # One ordinary access and one update warning per field is enough; a
        # dynamic record is commonly read several times in the same method.
        key = ("update" if augmented else "access", node.attr)
        if key in seen:
            continue
        seen.add(key)
        if augmented:
            message = (
                f"Dynamic-model x2many update .{node.attr} += ...: collect ids and assign"
                f" record[{node.attr!r}] = [Command.set(ids)] once"
            )
        else:
            message = (
                f"Field .{node.attr} is accessed on a record from env[<dynamic model>];"
                f" use record[{node.attr!r}] so the dynamic field access is explicit"
            )
        yield node.lineno, message


def _document_selection_fields(module, index):
    """Relations actually used as selectors in this module's view arches."""
    visible, type_domains = set(), set()

    def visit(node, model):
        if node.tag == "field" and node.get("name"):
            field = node.get("name")
            key = (model, field)
            visible.add(key)
            domain = node.get("domain", "")
            if re.search(r"\btype\b", domain):
                type_domains.add(key)
            comodels = index.comodels.get(key, set())
            nested_model = next(iter(comodels)) if len(comodels) == 1 else model
            for child in node:
                visit(child, nested_model)
            return
        for child in node:
            visit(child, model)

    for path in Path(module).rglob("*.xml"):
        try:
            root = etree.parse(str(path)).getroot()
        except (OSError, etree.XMLSyntaxError):
            continue
        for record in root.xpath(".//record[@model='ir.ui.view']"):
            model_node = record.find("field[@name='model']")
            arch = record.find("field[@name='arch']")
            if model_node is None or arch is None or not (model_node.text or "").strip():
                continue
            model = model_node.text.strip()
            for child in arch:
                visit(child, model)
    return visible, type_domains


def _document_relation_issues(tree, target_version, visible, type_domains):
    if target_version < 18:
        return
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef) or not fields._class_models(cls):
            continue
        for stmt in cls.body:
            call = getattr(stmt, "value", None)
            target = stmt.target if isinstance(stmt, ast.AnnAssign) else (
                stmt.targets[0]
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                else None
            )
            if not (
                isinstance(target, ast.Name)
                and isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr in {"Many2one", "Many2many"}
                and call.args
                and isinstance(call.args[0], ast.Constant)
                and call.args[0].value == "documents.document"
            ):
                continue
            model = fields._class_models(cls)[0]
            key = (model, target.id)
            if key not in visible or key in type_domains:
                continue
            domain = next((kw.value for kw in call.keywords if kw.arg == "domain"), None)
            mentions_type = domain is not None and any(
                isinstance(node, ast.Constant) and node.value == "type"
                for node in ast.walk(domain)
            )
            if not mentions_type:
                yield (
                    target.lineno,
                    (
                        f"{target.id} links to documents.document without a domain on type;"
                        " since Odoo 18 folders are documents with type='folder', add a domain"
                        " excluding folders when this field must select files only"
                    ),
                )


def _modal_models(module):
    result = set()
    for path in Path(module).rglob("*.xml"):
        try:
            root = etree.parse(str(path)).getroot()
        except (OSError, etree.XMLSyntaxError):
            continue
        for record in root.xpath(".//record[@model='ir.actions.act_window']"):
            values = {
                field.get("name"): "".join(field.itertext()).strip()
                for field in record.findall("field")
            }
            if values.get("target") == "new" and "form" in values.get("view_mode", ""):
                if values.get("res_model"):
                    result.add(values["res_model"])
    return result


def _persistent_wizard_issues(tree, index, modal_models):
    """Strong signs that a persistent model was intended to be a wizard."""
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        models_in_class = fields._class_models(cls)
        bases = {
            base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
            for base in cls.bases
        }
        if not models_in_class or "Model" not in bases or "TransientModel" in bases:
            continue
        model = models_in_class[0]
        explicitly_named = any(
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == "_name"
            for stmt in cls.body
        )
        if not explicitly_named:
            continue
        transient_lines = []
        for stmt in cls.body:
            target = stmt.target if isinstance(stmt, ast.AnnAssign) else (
                stmt.targets[0]
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                else None
            )
            call = getattr(stmt, "value", None)
            if not (
                isinstance(target, ast.Name)
                and isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "One2many"
            ):
                continue
            comodel = next(iter(index.comodels.get((model, target.id), set())), None)
            if comodel in index.transient:
                transient_lines.append((target.id, comodel))
        methods = {
            stmt.name
            for stmt in cls.body
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        modal_default = model in modal_models and "default_get" in methods
        if not transient_lines and not modal_default:
            continue
        evidence = []
        if model in modal_models:
            evidence.append("it is opened by a form action with target='new'")
        if "default_get" in methods:
            evidence.append("it defines default_get()")
        if transient_lines:
            relations = ", ".join(
                f"{field} -> {comodel}" for field, comodel in transient_lines
            )
            evidence.append(f"it has One2many relations to transient models ({relations})")
        yield (
            cls.lineno,
            f"{model} inherits models.Model but looks like a wizard: {'; '.join(evidence)};"
            " use models.TransientModel unless these records must persist",
        )


def check_module(module, index, target_version=20, precision_names=None):
    module = Path(module)
    closure = index.closure(module.name)
    complete = not index.unknown_dependencies(module.name)
    document_fields, document_type_domains = _document_selection_fields(module, index)
    modal_models = _modal_models(module)
    for path in models._python_files(module):
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, ValueError):
            continue
        visitor = Uses(index)
        visitor.visit(tree)
        for line, message in _dynamic_model_issues(tree):
            yield path, line, "warning", message
        for line, message in _document_relation_issues(
            tree, target_version, document_fields, document_type_domains
        ) or ():
            yield path, line, "warning", message
        for line, message in _persistent_wizard_issues(tree, index, modal_models):
            yield path, line, "warning", message
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
            elif (
                not owners
                and complete
                and ancestors <= index.defined
                and field not in models.MAGIC_FIELDS
                and not field.startswith("_")
                and field not in {"env", "ids"}
                and not any(field in index.methods.get(m, set()) for m in ancestors)
            ):
                yield (
                    path,
                    node.lineno,
                    "error",
                    f"Field {model}.{field} does not exist in the indexed target",
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
            if (
                target_version >= 20
                and field == "name"
                and model
                in {"sale.order.line", "purchase.order.line", "account.move.line"}
            ):
                yield (
                    path,
                    node.lineno,
                    "warning",
                    f"{model}.name no longer includes the product name in Odoo 20; use product_id.display_name when the product label is required (odoo c5037bbe0789)",
                )
        if target_version >= 20:
            for call in ast.walk(tree):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "_select_seller"
                ):
                    continue
                if not _seller_info_extracted(call, tree):
                    yield (
                        path,
                        call.lineno,
                        "error",
                        "_select_seller() returns a dict in Odoo 20; retrieve the record with result.get('supplierinfo', env['product.supplierinfo']) (odoo ab29b56cb6be)",
                    )
                positional_quantity = len(call.args) >= 2
                keyword_quantity = any(
                    keyword.arg == "quantity" for keyword in call.keywords
                )
                if not positional_quantity and not keyword_quantity:
                    yield (
                        path,
                        call.lineno,
                        "warning",
                        "_select_seller() called without quantity while product.supplierinfo.min_qty now defaults to 1 in Odoo 20; pass the quantity explicitly",
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
                ):
                    inherited_owners = set().union(
                        *(
                            index.method_owners.get((m, stmt.name), set())
                            for m in ancestors
                        )
                    ) - {module.name}
                    calls_same_super = any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == stmt.name
                        and isinstance(node.func.value, ast.Call)
                        and isinstance(node.func.value.func, ast.Name)
                        and node.func.value.func.id == "super"
                        for node in ast.walk(stmt)
                    )
                    if (
                        calls_same_super
                        and not inherited_owners
                        and complete
                        and ancestors <= index.defined
                    ):
                        inherited_methods = {
                            method
                            for ancestor in ancestors
                            for method in index.methods.get(ancestor, set())
                            if index.method_owners.get((ancestor, method), set())
                            - {module.name}
                        }
                        known = index.renamed_methods.get((model, stmt.name))
                        if known:
                            target, source = known
                            suggestion = f"; renamed to {target}"
                            if source:
                                suggestion += f" ({source})"
                        else:
                            close = difflib.get_close_matches(
                                stmt.name, sorted(inherited_methods), n=3, cutoff=0.4
                            )
                            suggestion = (
                                f"; possible target methods: {', '.join(close)}"
                                if close
                                else ""
                            )
                        yield (
                            path,
                            stmt.lineno,
                            "warning",
                            f"{model}.{stmt.name}() calls super(), but no parent method with that name exists in the indexed target{suggestion}",
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
