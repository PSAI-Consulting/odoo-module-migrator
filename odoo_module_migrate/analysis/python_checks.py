"""Conservative, model-aware checks of Python code against indexed addons."""

import ast
import difflib
import io
import re
import tokenize
from pathlib import Path

from lxml import etree

from . import fields, models


def _target_method_signature(index, ancestors, method, closure, module_name):
    """Return the single concrete signature inherited from target addons."""
    signatures = {}
    for ancestor in ancestors:
        for owner in index.method_owners.get((ancestor, method), set()):
            if owner in {module_name, "base"} or owner not in closure:
                continue
            for signature in index.method_signatures.get((ancestor, method, owner), ()):
                # A forwarding *args/**kwargs override gives no useful contract;
                # another concrete implementation in the MRO remains usable.
                if signature.get("vararg") or signature.get("kwarg"):
                    continue
                signatures[models.signature_key(signature)] = signature
    return next(iter(signatures.values())) if len(signatures) == 1 else None


def _same_super_calls(function):
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == function.name
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Name)
        and node.func.value.func.id == "super"
    ]


def _signature_problem(local, target, super_calls):
    """Explain a provable incompatibility with a target method contract."""
    if local.get("vararg") and local.get("kwarg"):
        return ""
    local_parameters = local["parameters"]
    target_parameters = target["parameters"]
    local_by_name = {item["name"]: item for item in local_parameters}
    target_names = [item["name"] for item in target_parameters]
    missing = [name for name in target_names if name not in local_by_name]
    shared_order = [
        item["name"] for item in local_parameters if item["name"] in target_names
    ]
    reordered = shared_order != [name for name in target_names if name in local_by_name]
    changed_kind = [
        item["name"]
        for item in target_parameters
        if item["name"] in local_by_name
        and local_by_name[item["name"]]["kind"] != item["kind"]
    ]
    changed_defaults = [
        item["name"]
        for item in target_parameters
        if item["name"] in local_by_name
        and local_by_name[item["name"]].get("default") != item.get("default")
    ]
    call_problems = []
    positional = [
        item for item in target_parameters if item["kind"] != "keyword_only"
    ]
    allowed_keywords = {item["name"] for item in target_parameters}
    required = {
        item["name"]
        for item in target_parameters
        if item.get("default") is None
    }
    for call in super_calls:
        if any(isinstance(argument, ast.Starred) for argument in call.args) or any(
            keyword.arg is None for keyword in call.keywords
        ):
            continue
        if len(call.args) > len(positional):
            call_problems.append(
                f"super() passes {len(call.args)} positional arguments but the target accepts {len(positional)}"
            )
        for position, argument in enumerate(call.args[: len(positional)]):
            if (
                isinstance(argument, ast.Name)
                and argument.id in local_by_name
                and argument.id != positional[position]["name"]
            ):
                call_problems.append(
                    f"positional argument {argument.id!r} is received as {positional[position]['name']!r}"
                )
        unknown = sorted(
            keyword.arg
            for keyword in call.keywords
            if keyword.arg is not None and keyword.arg not in allowed_keywords
        )
        if unknown:
            call_problems.append("super() passes removed keyword(s) " + ", ".join(unknown))
        passed = {
            positional[position]["name"]
            for position in range(min(len(call.args), len(positional)))
        } | {keyword.arg for keyword in call.keywords if keyword.arg}
        # Required parameters may deliberately be supplied by the target's
        # internal defaults only when they actually have a default.
        omitted = sorted(required - passed)
        if omitted:
            call_problems.append("super() omits required parameter(s) " + ", ".join(omitted))
    parts = []
    if missing:
        parts.append("missing target parameter(s) " + ", ".join(missing))
    if reordered:
        parts.append("target parameters are reordered")
    if changed_kind:
        parts.append("parameter kind changed for " + ", ".join(changed_kind))
    if changed_defaults:
        parts.append("target default changed for " + ", ".join(changed_defaults))
    parts.extend(dict.fromkeys(call_problems))
    return "; ".join(parts)


def _function_parameter_span(text, function, positions):
    """Offsets inside the parentheses of a function definition."""
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    started = named = False
    depth = 0
    opening = None
    for token in tokens:
        start = positions.offset(*token.start)
        if start < positions.offset(function.lineno, function.col_offset):
            continue
        if token.type == tokenize.NAME and token.string in {"def", "async"}:
            started = True
            continue
        if started and token.type == tokenize.NAME and token.string == function.name:
            named = True
            continue
        if not named or token.type != tokenize.OP:
            continue
        if token.string == "(":
            if depth == 0:
                opening = positions.offset(*token.end)
            depth += 1
        elif token.string == ")":
            depth -= 1
            if depth == 0 and opening is not None:
                return opening, positions.offset(*token.start)
    return None


def apply_override_signature_migrations(module, index):
    """Synchronize simple overrides whose old signature is unambiguous.

    The rewrite is deliberately narrow: simple positional parameters, one
    direct forwarding super call, literal target defaults, and removed
    parameters unused anywhere else in the method.
    """
    module = Path(module)
    closure = index.closure(module.name)
    changed = []
    for path in models._python_files(module):
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        positions = fields._Positions(text)
        edits = []
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            class_models = fields._class_models(cls)
            if not class_models:
                continue
            model = class_models[0]
            ancestors = index.ancestors(model)
            for function in cls.body:
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                target = _target_method_signature(
                    index, ancestors, function.name, closure, module.name
                )
                calls = _same_super_calls(function)
                if not target or len(calls) != 1:
                    continue
                local = models.method_signature(function)
                if not _signature_problem(local, target, calls):
                    continue
                if (
                    not function.args.args
                    or function.args.args[0].arg not in {"self", "cls"}
                    or function.args.posonlyargs
                    or function.args.vararg
                    or function.args.kwonlyargs
                    or function.args.kwarg
                    or any(
                        argument.annotation is not None
                        for argument in function.args.args
                    )
                    or any(item["kind"] != "positional_or_keyword" for item in target["parameters"])
                ):
                    continue
                local_names = [item["name"] for item in local["parameters"]]
                target_names = [item["name"] for item in target["parameters"]]
                if not set(target_names) <= set(local_names):
                    continue
                call = calls[0]
                forwards_positionally = (
                    not call.keywords
                    and [getattr(arg, "id", None) for arg in call.args] == local_names
                )
                forwards_by_name = (
                    not call.args
                    and len(call.keywords) == len(local_names)
                    and {
                        keyword.arg: getattr(keyword.value, "id", None)
                        for keyword in call.keywords
                    }
                    == {name: name for name in local_names}
                )
                if not (forwards_positionally or forwards_by_name):
                    continue
                removed = set(local_names) - set(target_names)
                if any(
                    sum(
                        isinstance(node, ast.Name)
                        and isinstance(node.ctx, ast.Load)
                        and node.id == name
                        for node in ast.walk(function)
                    )
                    != 1
                    for name in removed
                ):
                    continue
                rendered = []
                safe_defaults = True
                for item in target["parameters"]:
                    value = item["name"]
                    default = item.get("default")
                    if default is not None:
                        try:
                            ast.literal_eval(default)
                        except (SyntaxError, ValueError):
                            safe_defaults = False
                            break
                        value += "=" + default
                    rendered.append(value)
                span = _function_parameter_span(text, function, positions)
                if (
                    not safe_defaults
                    or not span
                    or "#" in text[span[0] : span[1]]
                ):
                    continue
                recordset = function.args.args[0].arg
                edits.append((*span, ", ".join([recordset, *rendered])))
                call_start = positions.offset(call.lineno, call.col_offset)
                call_end = positions.offset(call.end_lineno, call.end_col_offset)
                call_source = text[
                    positions.offset(call.func.lineno, call.func.col_offset) :
                    positions.offset(call.func.end_lineno, call.func.end_col_offset)
                ]
                edits.append(
                    (
                        call_start,
                        call_end,
                        call_source
                        + "("
                        + ", ".join(f"{name}={name}" for name in target_names)
                        + ")",
                    )
                )
                changed.append(
                    (
                        path,
                        function.lineno,
                        f"{model}.{function.name}{models.format_signature(local)} -> {models.format_signature(target)} and named super() arguments",
                    )
                )
        for start, end, replacement in sorted(edits, reverse=True):
            text = text[:start] + replacement + text[end:]
        if edits:
            path.write_text(text, encoding="utf-8")
    return changed


class Uses(ast.NodeVisitor):
    """Track recordset aliases and relational paths within a method."""

    def __init__(self, index, parameter_types=None, method_parameters=None):
        self.index = index
        self.aliases = {}
        self.usages = []
        self.model_uses = []
        self.called = set()
        self.method_calls = []
        self.super_results = {}
        self.parameter_types = parameter_types or {}
        self.method_parameters = method_parameters or {}

    def receiver(self, node):
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id)
        model = fields._env_model(node)
        if model:
            return model
        if isinstance(node, ast.Attribute):
            model = self.receiver(node.value)
            if node.attr == "_origin":
                return model
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
            and node.func.attr == "mapped"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            model = self.receiver(node.func.value)
            for field in node.args[0].value.split("."):
                candidates = (
                    set().union(
                        *(
                            self.index.comodels.get((ancestor, field), set())
                            for ancestor in self.index.ancestors(model)
                        )
                    )
                    if model
                    else set()
                )
                if len(candidates) != 1:
                    return None
                model = next(iter(candidates))
            return model
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
        saved = self.aliases, self.super_results
        names = fields._class_models(node)
        self.aliases = {"self": names[0]} if names else {}
        self.super_results = {}
        self.generic_visit(node)
        self.aliases, self.super_results = saved

    def visit_FunctionDef(self, node):
        saved = self.aliases.copy(), self.super_results.copy()
        model = self.aliases.get("self")
        if model:
            for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                candidates = self.parameter_types.get((model, node.name, argument.arg), set())
                if len(candidates) == 1:
                    self.aliases[argument.arg] = next(iter(candidates))
        self.generic_visit(node)
        self.aliases, self.super_results = saved

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node):
        self.visit(node.value)
        model = self.receiver(node.value)
        for target in node.targets:
            self.visit(target)
            if isinstance(target, ast.Name):
                self.aliases.pop(target.id, None)
                self.super_results.pop(target.id, None)
                if model:
                    self.aliases[target.id] = model
                elif (
                    isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and isinstance(node.value.func.value, ast.Call)
                    and isinstance(node.value.func.value.func, ast.Name)
                    and node.value.func.value.func.id == "super"
                    and self.aliases.get("self")
                ):
                    self.super_results[target.id] = self.aliases["self"]

    def visit_For(self, node):
        self.visit(node.iter)
        saved = self.aliases.copy()
        if isinstance(node.target, ast.Name):
            self.aliases.pop(node.target.id, None)
            model = self.receiver(node.iter) or (
                self.super_results.get(node.iter.id)
                if isinstance(node.iter, ast.Name)
                else None
            )
            if model:
                self.aliases[node.target.id] = model
        for stmt in node.body + node.orelse:
            self.visit(stmt)
        self.aliases = saved

    def _visit_comprehension(self, node, values):
        saved = self.aliases.copy()
        for generator in node.generators:
            self.visit(generator.iter)
            model = self.receiver(generator.iter)
            if isinstance(generator.target, ast.Name):
                self.aliases.pop(generator.target.id, None)
                if model:
                    self.aliases[generator.target.id] = model
            else:
                self.visit(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        for value in values:
            self.visit(value)
        self.aliases = saved

    def visit_GeneratorExp(self, node):
        self._visit_comprehension(node, [node.elt])

    visit_ListComp = visit_GeneratorExp
    visit_SetComp = visit_GeneratorExp

    def visit_DictComp(self, node):
        self._visit_comprehension(node, [node.key, node.value])

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
            if model:
                self.method_calls.append((node.func, model, node.func.attr))
                names = self.method_parameters.get((model, node.func.attr), ())
                for name, argument in zip(names, node.args):
                    argument_model = self.receiver(argument)
                    if argument_model:
                        self.parameter_types.setdefault(
                            (model, node.func.attr, name), set()
                        ).add(argument_model)
                for keyword in node.keywords:
                    argument_model = self.receiver(keyword.value)
                    if keyword.arg and argument_model:
                        self.parameter_types.setdefault(
                            (model, node.func.attr, keyword.arg), set()
                        ).add(argument_model)
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


def analyze_uses(tree, index):
    """Resolve local aliases, then propagate typed keyword arguments once."""
    method_parameters = {}
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        class_models = fields._class_models(cls)
        if not class_models:
            continue
        for statement in cls.body:
            if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            arguments = [*statement.args.posonlyargs, *statement.args.args]
            if arguments and arguments[0].arg in {"self", "cls"}:
                arguments = arguments[1:]
            method_parameters[(class_models[0], statement.name)] = tuple(
                argument.arg for argument in arguments
            )
    parameter_types = {}
    visitor = None
    for _iteration in range(max(2, len(method_parameters) + 1)):
        before = {key: frozenset(value) for key, value in parameter_types.items()}
        visitor = Uses(index, parameter_types, method_parameters)
        visitor.visit(tree)
        parameter_types = visitor.parameter_types
        after = {key: frozenset(value) for key, value in parameter_types.items()}
        if after == before and _iteration:
            break
    final = Uses(index, parameter_types, method_parameters)
    final.visit(tree)
    return final


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
        visitor = analyze_uses(tree, index)
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


def apply_binaryvalue_migrations(module, index):
    """Apply only model-proven Odoo 20 BinaryValue conversions."""
    changed = []
    for path in models._python_files(Path(module)):
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        visitor = analyze_uses(tree, index)
        resolved = {id(node): (model, field) for node, model, field in visitor.usages}
        call_models = {id(node): model for node, model, _method in visitor.method_calls}
        parents = {
            id(child): parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        positions = fields._Positions(text)
        edits = []
        needs_import = False

        def source(node):
            return text[
                positions.offset(node.lineno, node.col_offset) :
                positions.offset(node.end_lineno, node.end_col_offset)
            ]

        def binary(info):
            return bool(info and _field_kind(index, *info) & {"Binary", "Image"})

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                receiver_info = resolved.get(id(node.func.value))
                if node.func.attr == "decode" and binary(receiver_info):
                    encoding = None
                    if node.args:
                        encoding = (
                            node.args[0].value
                            if isinstance(node.args[0], ast.Constant)
                            and isinstance(node.args[0].value, str)
                            else False
                        )
                    else:
                        encoding_kw = next(
                            (kw.value for kw in node.keywords if kw.arg == "encoding"),
                            None,
                        )
                        if encoding_kw is not None:
                            encoding = (
                                encoding_kw.value
                                if isinstance(encoding_kw, ast.Constant)
                                and isinstance(encoding_kw.value, str)
                                else False
                            )
                    if encoding is None or (
                        isinstance(encoding, str)
                        and encoding.lower().replace("_", "-")
                        in {"utf-8", "utf8", "ascii"}
                    ):
                        edits.append(
                            (
                                positions.offset(node.lineno, node.col_offset),
                                positions.offset(node.end_lineno, node.end_col_offset),
                                source(node.func.value) + ".to_base64()",
                                node.lineno,
                                "preserve BinaryValue base64 text",
                            )
                        )
                        continue
            if not (
                isinstance(node, ast.Call)
                and len(node.args) == 1
                and not node.keywords
            ):
                continue
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            replacement = None
            detail = ""
            if name == "b64decode" and binary(resolved.get(id(node.args[0]))):
                replacement = source(node.args[0]) + ".content"
                detail = "read BinaryValue.content"
            elif name == "b64encode":
                target_info = None
                parent = parents.get(id(node))
                if isinstance(parent, (ast.Assign, ast.AnnAssign)):
                    targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
                    target_info = next(
                        (resolved.get(id(target)) for target in targets if binary(resolved.get(id(target)))),
                        None,
                    )
                elif isinstance(parent, ast.Dict):
                    for key, value in zip(parent.keys, parent.values):
                        if value is not node or not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                            continue
                        call = parents.get(id(parent))
                        while call is not None and not isinstance(call, ast.Call):
                            call = parents.get(id(call))
                        model = (
                            call_models.get(id(call.func))
                            if isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr in {"create", "write", "update"}
                            else None
                        )
                        if model and binary((model, key.value)):
                            target_info = (model, key.value)
                if target_info:
                    replacement = f"BinaryBytes({source(node.args[0])})"
                    detail = "write BinaryBytes"
                    needs_import = True
            if replacement:
                edits.append(
                    (
                        positions.offset(node.lineno, node.col_offset),
                        positions.offset(node.end_lineno, node.end_col_offset),
                        replacement,
                        node.lineno,
                        detail,
                    )
                )
        if not edits:
            continue
        for start, end, replacement, _line, _detail in sorted(edits, reverse=True):
            text = text[:start] + replacement + text[end:]
        if needs_import and not re.search(
            r"^\s*from\s+odoo\.tools\.binary\s+import\s+.*\bBinaryBytes\b",
            text,
            re.M,
        ):
            body = ast.parse(text).body
            line = body[0].lineno - 1 if body else 0
            if body and isinstance(body[0], ast.Expr) and isinstance(
                body[0].value, ast.Constant
            ) and isinstance(body[0].value.value, str):
                line = body[0].end_lineno
            for statement in body:
                if isinstance(statement, ast.ImportFrom) and statement.module == "__future__":
                    line = max(line, statement.end_lineno)
            lines = text.splitlines(keepends=True)
            lines.insert(line, "from odoo.tools.binary import BinaryBytes\n")
            text = "".join(lines)
        path.write_text(text, encoding="utf-8")
        changed.extend((path, line, detail) for *_rest, line, detail in edits)
    return changed


def apply_runtime_api_migrations(module, index, target_version):
    """Apply model-proven runtime API migrations without changing labels."""
    if target_version < 18:
        return []
    changed = []
    for path in models._python_files(Path(module)):
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        visitor = analyze_uses(tree, index)
        resolved = {id(node): (model, field) for node, model, field in visitor.usages}
        call_models = {id(node): model for node, model, _method in visitor.method_calls}
        parents = {
            id(child): parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        positions = fields._Positions(text)
        edits = []

        def source(node):
            return text[
                positions.offset(node.lineno, node.col_offset) :
                positions.offset(node.end_lineno, node.end_col_offset)
            ]

        def add_edit(node, replacement, detail):
            edits.append(
                (
                    positions.offset(node.lineno, node.col_offset),
                    positions.offset(node.end_lineno, node.end_col_offset),
                    replacement,
                    node.lineno,
                    detail,
                )
            )

        def immediately_after_commit(node):
            statement = node
            while id(statement) in parents and not isinstance(
                statement, (ast.Expr, ast.Assign, ast.AnnAssign)
            ):
                statement = parents[id(statement)]
            block = parents.get(id(statement))
            body = getattr(block, "body", ())
            if statement not in body:
                return False
            position = body.index(statement)
            if position == 0:
                return False
            previous = body[position - 1]
            return any(
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and item.func.attr == "commit"
                for item in ast.walk(previous)
            )

        def singleton_receiver(receiver, node):
            info = resolved.get(id(receiver))
            if info and "Many2one" in _field_kind(index, *info):
                return True
            if isinstance(receiver, ast.Name):
                if any(
                    isinstance(usage, ast.Attribute)
                    and isinstance(usage.value, ast.Name)
                    and usage.value.id == receiver.id
                    and _field_kind(index, usage_model, usage_field)
                    - {"One2many", "Many2many"}
                    for usage, usage_model, usage_field in visitor.usages
                ):
                    return True
                current = node
                while id(current) in parents:
                    current = parents[id(current)]
                    if (
                        isinstance(current, ast.For)
                        and isinstance(current.target, ast.Name)
                        and current.target.id == receiver.id
                    ):
                        return True
            return False

        def config_parameter_call(node):
            return (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"get_param", "set_param"}
                and call_models.get(id(node.func)) == "ir.config_parameter"
            )

        handled_config_calls = set()

        if target_version >= 20:
            # Since Odoo 20 commit b84ffce402d3, ordinary Char fields named
            # name/x_name default to mark_as_copy(), while previous versions
            # copied their value unchanged. An explicit copy=True restores the
            # old behavior without requiring us to predict every copy path.
            for cls in (
                item for item in ast.walk(tree) if isinstance(item, ast.ClassDef)
            ):
                declarations = {
                    statement.targets[0].id
                    for statement in cls.body
                    if isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                }
                sql_view = any(
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and statement.targets[0].id == "_auto"
                    and isinstance(statement.value, ast.Constant)
                    and statement.value.value is False
                    for statement in cls.body
                )
                if "_name" not in declarations or sql_view:
                    continue
                class_models = fields._class_models(cls)
                if not class_models:
                    continue
                model = class_models[0]
                for statement in cls.body:
                    if not (
                        isinstance(statement, ast.Assign)
                        and len(statement.targets) == 1
                        and isinstance(statement.targets[0], ast.Name)
                        and statement.targets[0].id in {"name", "x_name"}
                        and isinstance(statement.value, ast.Call)
                        and isinstance(statement.value.func, ast.Attribute)
                        and isinstance(statement.value.func.value, ast.Name)
                        and statement.value.func.value.id == "fields"
                        and statement.value.func.attr == "Char"
                    ):
                        continue
                    call = statement.value
                    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
                    field_name = statement.targets[0].id
                    inherited_field = any(
                        field_name in index.fields.get(parent, set())
                        for parent in index.ancestors(model) - {model}
                    )
                    if (
                        inherited_field
                        or "copy" in keywords
                        or {"compute", "related", "company_dependent"} & keywords.keys()
                        or any(keyword.arg is None for keyword in call.keywords)
                        or any(isinstance(arg, ast.Starred) for arg in call.args)
                    ):
                        continue
                    translate = keywords.get("translate")
                    if translate is not None and not (
                        isinstance(translate, ast.Constant)
                        and isinstance(translate.value, bool)
                    ):
                        continue
                    arguments = [*call.args, *(keyword.value for keyword in call.keywords)]
                    if arguments:
                        last = arguments[-1]
                        offset = positions.offset(last.end_lineno, last.end_col_offset)
                        insertion = ", copy=True"
                    else:
                        offset = positions.offset(
                            call.func.end_lineno, call.func.end_col_offset
                        ) + 1
                        insertion = "copy=True"
                    edits.append(
                        (
                            offset,
                            offset,
                            insertion,
                            statement.lineno,
                            f"preserve copied {field_name} without '(copy)' suffix",
                        )
                    )

            # Preserve the old coercion while selecting Odoo 20's typed API.
            for outer in ast.walk(tree):
                if not (
                    isinstance(outer, ast.Call)
                    and isinstance(outer.func, ast.Name)
                    and outer.func.id in {"int", "float"}
                    and len(outer.args) == 1
                    and not outer.keywords
                ):
                    continue
                value = outer.args[0]
                default = None
                inner = value
                if (
                    isinstance(value, ast.BoolOp)
                    and isinstance(value.op, ast.Or)
                    and len(value.values) == 2
                ):
                    inner, default = value.values
                if not (
                    config_parameter_call(inner)
                    and inner.func.attr == "get_param"
                    and len(inner.args) == 1
                    and not inner.keywords
                ):
                    continue
                if default is not None:
                    if not isinstance(default, ast.Constant):
                        continue
                    if outer.func.id == "int" and (
                        not isinstance(default.value, int)
                        or isinstance(default.value, bool)
                    ):
                        continue
                    if outer.func.id == "float" and not isinstance(
                        default.value, (int, float)
                    ):
                        continue
                receiver = source(inner.func.value)
                arguments = ", ".join(source(arg) for arg in inner.args)
                standard_default = default is not None and default.value in {0, 0.0}
                if default is not None and not standard_default:
                    arguments += f", {source(default)}"
                add_edit(
                    outer,
                    f"{receiver}.get_{outer.func.id}({arguments})",
                    f"replace get_param with get_{outer.func.id}",
                )
                handled_config_calls.add(id(inner))

            for node in ast.walk(tree):
                if not config_parameter_call(node) or id(node) in handled_config_calls:
                    continue
                receiver = source(node.func.value)
                if node.func.attr == "set_param":
                    if len(node.args) < 2:
                        continue
                    value = node.args[1]
                    if isinstance(value, ast.Constant):
                        kind = (
                            "bool" if isinstance(value.value, bool)
                            else "int" if isinstance(value.value, int)
                            else "float" if isinstance(value.value, float)
                            else "str" if isinstance(value.value, str)
                            else None
                        )
                    elif (
                        isinstance(value, ast.Call)
                        and isinstance(value.func, ast.Name)
                        and value.func.id in {"bool", "int", "float", "str"}
                    ):
                        kind = value.func.id
                    else:
                        kind = None
                    if kind:
                        add_edit(
                            node.func,
                            f"{receiver}.set_{kind}",
                            f"replace set_param with set_{kind}",
                        )
                    continue
                parent = parents.get(id(node))
                replacement_node = node.func
                if (
                    isinstance(parent, ast.Compare)
                    and len(parent.ops) == 1
                    and isinstance(parent.ops[0], (ast.Eq, ast.NotEq))
                    and len(parent.comparators) == 1
                    and isinstance(parent.comparators[0], ast.Constant)
                    and parent.comparators[0].value == "True"
                    and len(node.args) == 1
                    and not node.keywords
                ):
                    positive = isinstance(parent.ops[0], ast.Eq)
                    call = f"{receiver}.get_bool({source(node.args[0])})"
                    add_edit(
                        parent,
                        call if positive else f"not {call}",
                        "replace boolean get_param comparison",
                    )
                    handled_config_calls.add(id(node))
                    continue
                if (
                    isinstance(parent, ast.BoolOp)
                    and isinstance(parent.op, ast.Or)
                    and len(parent.values) == 2
                    and parent.values[0] is node
                    and isinstance(parent.values[1], ast.Constant)
                    and isinstance(parent.values[1].value, str)
                    and len(node.args) == 1
                ):
                    add_edit(
                        parent,
                        f"{receiver}.get_str({source(node.args[0])}, {source(parent.values[1])})",
                        "replace get_param string default",
                    )
                    handled_config_calls.add(id(node))
                    continue
                add_edit(
                    replacement_node,
                    f"{receiver}.get_str",
                    "replace get_param with get_str",
                )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if (
                target_version >= 20
                and node.func.attr in {"clear", "reset"}
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "cr"
                and immediately_after_commit(node)
            ):
                add_edit(
                    node,
                    source(node.func.value.value) + ".transaction.clear()",
                    "replace Cursor.clear/reset after commit",
                )
                continue
            if node.func.attr != "name_get" or node.args or node.keywords:
                continue
            parent = parents.get(id(node))
            if not (
                isinstance(parent, ast.Subscript)
                and isinstance(parent.slice, ast.Constant)
                and parent.slice.value == 0
                and singleton_receiver(node.func.value, node)
            ):
                continue
            receiver = source(node.func.value)
            add_edit(
                parent,
                f"({receiver}.id, {receiver}.display_name)",
                "replace removed singleton name_get()[0]",
            )

        for mapping in (node for node in ast.walk(tree) if isinstance(node, ast.Dict)):
            values = {
                key.value: value
                for key, value in zip(mapping.keys, mapping.values)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            call = parents.get(id(mapping))
            while call is not None and not isinstance(call, ast.Call):
                call = parents.get(id(call))
            model = (
                call_models.get(id(call.func))
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                else None
            )
            type_value = values.get("type")
            if (
                isinstance(type_value, ast.Constant)
                and type_value.value == "tree"
                and (model == "ir.ui.view" or {"arch", "arch_base"} & values.keys())
            ):
                add_edit(type_value, repr("list"), "replace Python ir.ui.view type tree")
            view_mode = values.get("view_mode")
            if (
                model == "ir.actions.act_window"
                and isinstance(view_mode, ast.Constant)
                and isinstance(view_mode.value, str)
                and "tree" in view_mode.value.split(",")
            ):
                modes = ["list" if mode.strip() == "tree" else mode.strip() for mode in view_mode.value.split(",")]
                add_edit(view_mode, repr(",".join(modes)), "replace Python action view_mode tree")

        if target_version >= 20:
            for cls in (
                node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
            ):
                class_models = fields._class_models(cls)
                if not class_models:
                    continue
                known_fields = set().union(
                    *(
                        index.fields.get(ancestor, set())
                        for ancestor in index.ancestors(class_models[0])
                    )
                )
                for method in cls.body:
                    if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if any(
                        isinstance(item, ast.Call)
                        and isinstance(item.func, ast.Attribute)
                        and isinstance(item.func.value, ast.Name)
                        and item.func.value.id == "self"
                        and item.func.attr == "ensure_one"
                        for item in ast.walk(method)
                    ):
                        continue
                    for loop in (
                        item for item in ast.walk(method) if isinstance(item, ast.For)
                    ):
                        if not (
                            isinstance(loop.iter, ast.Name)
                            and loop.iter.id == "self"
                            and isinstance(loop.target, ast.Name)
                        ):
                            continue
                        for statement in loop.body:
                            for item in ast.walk(statement):
                                if (
                                    isinstance(item, ast.Attribute)
                                    and isinstance(item.ctx, ast.Load)
                                    and isinstance(item.value, ast.Name)
                                    and item.value.id == "self"
                                    and item.attr in known_fields
                                ):
                                    add_edit(
                                        item.value,
                                        loop.target.id,
                                        f"use loop record for field {item.attr}",
                                    )
        if not edits:
            continue
        # A parent replacement subsumes edits below it (not expected by these
        # rules, but filtering keeps the generic editor deterministic).
        selected = []
        for edit in sorted(edits, key=lambda item: (item[0], -item[1])):
            if any(start <= edit[0] and edit[1] <= end for start, end, *_ in selected):
                continue
            selected.append(edit)
        for start, end, replacement, _line, _detail in sorted(selected, reverse=True):
            text = text[:start] + replacement + text[end:]
        path.write_text(text, encoding="utf-8")
        changed.extend((path, line, detail) for *_rest, line, detail in selected)
    return changed


def dependency_message(index, module, what, owners):
    owners = sorted(owners)
    if set(owners) <= index.enterprise_modules:
        return (
            f"{what}: Enterprise provider {', '.join(owners)} is not added "
            "automatically; review the feature and add it explicitly if intended"
        )
    circular = [owner for owner in owners if module in index.closure(owner)]
    if len(circular) == len(owners):
        return f"{what}: circular dependency; move this code into {', '.join(circular)} (field/model provider) or a bridge module"
    return f"{what}: add a provider to 'depends': {', '.join(o for o in owners if o not in circular)}"


def apply_unambiguous_dependencies(module, index, with_manual=False):
    """Add safe Python providers and retain Enterprise providers for review."""
    module = Path(module)
    if index.unknown_dependencies(module.name):
        return ([], []) if with_manual else []
    closure = index.closure(module.name)
    providers = set()
    manual = set()

    def result(additions):
        if not with_manual:
            return additions
        return additions, sorted(
            manual, key=lambda item: (str(item[0]), *item[1:])
        )

    def consider(owners, symbol, path, line):
        owners = set(owners)
        if owners & closure:
            return
        if len(owners) != 1:
            return
        owner = next(iter(owners))
        if owner in index.enterprise_modules:
            manual.add((path, line, owner, symbol))
        elif owner in index.depends and module.name not in index.closure(owner):
            providers.add(owner)

    for path in models._python_files(module):
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, ValueError):
            continue
        visitor = analyze_uses(tree, index)
        for node, model in visitor.model_uses:
            consider(index.owners(model), f"model {model}", path, node.lineno)
        for node, model, field in visitor.usages:
            consider(
                set().union(
                    *(
                        index.field_owners.get((ancestor, field), set())
                        for ancestor in index.ancestors(model)
                    )
                ),
                f"field {model}.{field}",
                path,
                node.lineno,
            )
        for node, model, method in visitor.method_calls:
            consider(
                set().union(
                    *(
                        index.method_owners.get((ancestor, method), set())
                        for ancestor in index.ancestors(model)
                    )
                ),
                f"method {model}.{method}()",
                path,
                node.lineno,
            )
    if not providers:
        return result([])
    manifest_path = module / "__manifest__.py"
    text = manifest_path.read_text(encoding="utf-8", errors="replace")
    try:
        data = ast.literal_eval(text.lstrip())
        dependencies = list(data.get("depends", []))
        additions = sorted(providers - set(dependencies))
        if not additions:
            return []
        from ..manifest import rewrite_list

        text = rewrite_list(text, "depends", dependencies + additions)
    except (OSError, SyntaxError, ValueError, TypeError):
        return result([])
    manifest_path.write_text(text, encoding="utf-8")
    index.depends[module.name] = dependencies + additions
    return result(additions)


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


def _searched_models(module):
    result = set()
    for path in models._python_files(module):
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"search", "search_count"}
            ):
                model = fields._env_model(node.func.value)
                if model:
                    result.add(model)
    return result


def _persistent_wizard_issues(tree, index, modal_models, searched_models=()):
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
        if model in searched_models:
            continue
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


def _html_field_issues(tree, index):
    """Markup-sensitive updates and malformed break tags in model code."""
    seen_breaks = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "</br>" in node.value.lower()
            and node.lineno not in seen_breaks
        ):
            seen_breaks.add(node.lineno)
            yield (
                node.lineno,
                "Malformed HTML closing tag </br>; use <br> or <br/> for a line break",
            )
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        class_models = fields._class_models(cls)
        if not class_models:
            continue
        html_fields = {
            field
            for model in index.ancestors(class_models[0])
            for field in index.fields.get(model, set())
            if "Html" in index.field_types.get((model, field), set())
        }
        if not html_fields:
            continue
        for node in ast.walk(cls):
            if (
                isinstance(node, ast.AugAssign)
                and isinstance(node.target, ast.Attribute)
                and node.target.attr in html_fields
            ):
                yield (
                    node.lineno,
                    f"HTML field {node.target.attr} is extended with +=; its current value is"
                    " Markup, so a plain string is escaped. Build one Markup template with"
                    " escaped interpolated values and assign the field once",
                )


def _field_kind(index, model, field):
    return set().union(
        *(index.field_types.get((ancestor, field), set()) for ancestor in index.ancestors(model))
    )


def _multi_record_self_issues(tree, index):
    """Find field reads on self inside an explicit `for record in self`."""
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        class_models = fields._class_models(cls)
        if not class_models:
            continue
        model = class_models[0]
        known_fields = set().union(
            *(index.fields.get(ancestor, set()) for ancestor in index.ancestors(model))
        )
        for method in cls.body:
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            ensured = any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
                and node.func.attr == "ensure_one"
                for node in ast.walk(method)
            )
            if ensured:
                continue
            for loop in (node for node in ast.walk(method) if isinstance(node, ast.For)):
                if not (
                    isinstance(loop.iter, ast.Name)
                    and loop.iter.id == "self"
                    and isinstance(loop.target, ast.Name)
                ):
                    continue
                variable = loop.target.id
                seen = set()
                for statement in loop.body:
                    for node in ast.walk(statement):
                        if (
                            isinstance(node, ast.Attribute)
                            and isinstance(node.ctx, ast.Load)
                            and isinstance(node.value, ast.Name)
                            and node.value.id == "self"
                            and node.attr in known_fields
                            and node.attr not in seen
                        ):
                            seen.add(node.attr)
                            yield (
                                node.lineno,
                                f"self.{node.attr} reads a field inside `for {variable} in self`; "
                                f"use {variable}.{node.attr} to avoid Expected singleton on multi-record calls",
                            )


def _odoo20_python_issues(tree, index, visitor):
    """Certain Python incompatibilities introduced by the Odoo 20 ORM APIs."""
    parents = {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    resolved = {id(node): (model, field) for node, model, field in visitor.usages}
    call_models = {id(node): model for node, model, _method in visitor.method_calls}
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, (ast.Constant, ast.JoinedStr)):
            value = node.exc.value if isinstance(node.exc, ast.Constant) else ""
            if isinstance(node.exc, ast.JoinedStr) or isinstance(value, str):
                yield node.lineno, "error", "Python cannot raise a string; raise UserError(...) or another Exception instance"
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            yield node.lineno, "warning", "Bare except catches system-exiting exceptions; catch Exception or the expected exception types"
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Add)
            and (
                isinstance(node.left, ast.Constant) and isinstance(node.left.value, str)
                and isinstance(node.right, ast.Attribute) and node.right.attr == "content"
                or isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)
                and isinstance(node.left, ast.Attribute) and node.left.attr == "content"
            )
        ):
            yield node.lineno, "error", "Text is concatenated with .content, which is commonly bytes (for example requests.Response.content); decode it or use .text"
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name in {"get_param", "set_param"}:
            replacement = "get_str/get_int/get_float/get_bool" if name == "get_param" else "set_str/set_int/set_float/set_bool"
            yield node.lineno, "error", f"ir.config_parameter.{name}() was removed in Odoo 20; choose the typed {replacement} method matching the value"
        if name == "_file_read" and node.args:
            yield node.lineno, "error", "ir.attachment._file_read() no longer accepts store_fname in Odoo 20; call it on the attachment without arguments (it returns BinaryValue)"
        if (
            name in {"clear", "reset"}
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "cr"
        ):
            yield node.lineno, "error", "Cursor.clear()/reset() was removed in Odoo 20; use env.transaction.clear(), and also clear cr.precommit when pending precommit callbacks must be discarded"
        if name == "execute" and node.args and isinstance(node.args[0], ast.Constant):
            sql = node.args[0].value
            if isinstance(sql, str) and re.search(r"\bmail_tracking_value\b", sql, re.I):
                yield node.lineno, "error", "Raw SQL references mail_tracking_value, whose model moved to optional mail_tracking in Odoo 20; rely on ORM/cascades or guard the table with table_exists()"
        if name in {"b64decode", "b64encode"} and node.args:
            info = resolved.get(id(node.args[0]))
            if info and _field_kind(index, *info) & {"Binary", "Image"}:
                action = "read field.content instead of base64-decoding it" if name == "b64decode" else "do not base64-encode an already binary field value"
                yield node.lineno, "error", f"Odoo 20 Binary/Image values use BinaryValue; {action}"
        if name == "decode" and isinstance(node.func, ast.Attribute):
            info = resolved.get(id(node.func.value))
            if info and _field_kind(index, *info) & {"Binary", "Image"}:
                yield (
                    node.lineno,
                    "warning",
                    "decode() on an Odoo 20 BinaryValue decodes the raw file, while older Binary fields held base64 bytes; use to_base64() to preserve a base64 payload, or .content.decode(encoding) when decoded file text is intended",
                )
        if name == "b64encode":
            parent = parents.get(id(node))
            if isinstance(parent, (ast.Assign, ast.AnnAssign)):
                targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
                for target in targets:
                    info = resolved.get(id(target))
                    if info and _field_kind(index, *info) & {"Binary", "Image"}:
                        yield node.lineno, "error", "base64.b64encode() returns bytes, which cannot be assigned to a Binary/Image field in Odoo 20; use BinaryBytes(raw) or decode the base64 result to str"
        if name in {"create", "write", "update"} and node.args:
            model = call_models.get(id(node.func))
            mappings = node.args[0].elts if isinstance(node.args[0], (ast.List, ast.Tuple)) else [node.args[0]]
            for mapping in mappings:
                if not model or not isinstance(mapping, ast.Dict):
                    continue
                for key, value in zip(mapping.keys, mapping.values):
                    if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                        continue
                    if not (_field_kind(index, model, key.value) & {"Binary", "Image"}):
                        continue
                    value_name = value.func.attr if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) else getattr(getattr(value, "func", None), "id", "")
                    if value_name == "b64encode":
                        yield value.lineno, "error", f"base64.b64encode() returns bytes for Binary/Image field {model}.{key.value}; use BinaryBytes(raw) or decode the base64 result to str"
        if (
            name == "get"
            and isinstance(node.func, ast.Attribute)
            and (
                isinstance(node.func.value, ast.Name) and node.func.value.id == "env"
                or isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "env"
            )
            and isinstance(parents.get(id(node)), (ast.If, ast.IfExp, ast.UnaryOp, ast.BoolOp))
        ):
            yield node.lineno, "warning", "env.get(model) returns a recordset; a missing/empty model is false. Use `model in env` to test registry membership"
        if (
            isinstance(node.func, ast.Name) and node.func.id == "isinstance"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Attribute)
            and isinstance(node.args[1].value, ast.Name)
            and node.args[1].value.id == "fields"
        ):
            yield node.lineno, "warning", "isinstance(record.value, fields.X) compares a field value with a field descriptor class; inspect record._fields[name].type instead"

    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        class_models = fields._class_models(cls)
        if not class_models:
            continue
        computed = {}
        for stmt in cls.body:
            target = stmt.target if isinstance(stmt, ast.AnnAssign) else (
                stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None
            )
            call = getattr(stmt, "value", None)
            if isinstance(target, ast.Name) and isinstance(call, ast.Call):
                compute = next((kw.value.value for kw in call.keywords if kw.arg == "compute" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)), None)
                if compute:
                    computed.setdefault(compute, set()).add(target.id)
        for stmt in cls.body:
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = {
                deco.attr for deco in stmt.decorator_list if isinstance(deco, ast.Attribute)
            }
            if stmt.name == "create" and "model_create_multi" not in decorators:
                yield stmt.lineno, "warning", "create() override lacks @api.model_create_multi; accept vals_list and handle every dictionary before calling super()"
            fields_for_compute = computed.get(stmt.name, set())
            if fields_for_compute:
                for assignment in ast.walk(stmt):
                    targets = []
                    if isinstance(assignment, ast.Assign):
                        targets = assignment.targets
                    elif isinstance(assignment, (ast.AnnAssign, ast.AugAssign)):
                        targets = [assignment.target]
                    for target in targets:
                        if isinstance(target, ast.Attribute) and target.attr not in fields_for_compute:
                            yield target.lineno, "warning", f"Compute {stmt.name} writes other field {target.attr}; clearing a user-entered field during compute may be ignored during create and can leave the original value stored"
                            break
            auth_none = any(
                isinstance(deco, ast.Call)
                and (getattr(deco.func, "attr", "") == "route" or getattr(deco.func, "id", "") == "route")
                and any(kw.arg == "auth" and isinstance(kw.value, ast.Constant) and kw.value.value == "none" for kw in deco.keywords)
                for deco in stmt.decorator_list
            )
            if auth_none:
                for call in ast.walk(stmt):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in {"message_post", "activity_schedule"}:
                        if not any(isinstance(part, ast.Call) and isinstance(part.func, ast.Attribute) and part.func.attr == "with_user" for part in ast.walk(call.func.value)):
                            yield call.lineno, "warning", f"{call.func.attr}() in an auth='none' route has no request user; call it with an explicit user (for example with_user(SUPERUSER_ID))"


_SQL_KEYWORDS = {
    "cross", "full", "group", "inner", "join", "left", "limit", "on",
    "order", "outer", "right", "union", "where",
}


def _removed_sql_field_issues(tree, removed_fields):
    """Find qualified references to known removed ORM fields in raw SQL."""
    rules = {}
    for rule in removed_fields or ():
        if len(rule) < 2:
            continue
        model, field = rule[:2]
        source = rule[2] if len(rule) > 2 else "migration rule"
        rules.setdefault(model.replace(".", "_").lower(), {}).setdefault(
            field.lower(), (model, source)
        )
    if not rules:
        return
    table_pattern = re.compile(
        r'\b(?:FROM|JOIN)\s+(?:"?[A-Za-z_]\w*"?\.)?"?([A-Za-z_]\w*)"?'
        r'(?:\s+(?:AS\s+)?"?([A-Za-z_]\w*)"?)?',
        re.IGNORECASE,
    )
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and re.search(r"\b(?:SELECT|UPDATE|DELETE\s+FROM|INSERT\s+INTO)\b", node.value, re.I)
        ):
            continue
        aliases = {}
        for match in table_pattern.finditer(node.value):
            table, alias = match.groups()
            normalized_table = table.lower()
            if normalized_table not in rules:
                continue
            aliases[table] = normalized_table
            if alias and alias.lower() not in _SQL_KEYWORDS:
                aliases[alias] = normalized_table
        seen = set()
        for alias, table in aliases.items():
            for field, (model, source) in rules[table].items():
                pattern = re.compile(
                    rf'\b{re.escape(alias)}\s*\.\s*"?{re.escape(field)}"?\b',
                    re.IGNORECASE,
                )
                for match in pattern.finditer(node.value):
                    key = (match.start(), model, field)
                    if key in seen:
                        continue
                    seen.add(key)
                    line = node.lineno + node.value.count("\n", 0, match.start())
                    yield (
                        line,
                        "error",
                        f"Raw SQL references removed field {model}.{field}; replace the column using its target semantics ({source})",
                    )


def check_module(
    module, index, target_version=20, precision_names=None, removed_fields=()
):
    module = Path(module)
    closure = index.closure(module.name)
    complete = not index.unknown_dependencies(module.name)
    document_fields, document_type_domains = _document_selection_fields(module, index)
    modal_models = _modal_models(module)
    searched_models = _searched_models(module)
    for path in models._python_files(module):
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, ValueError):
            continue
        visitor = analyze_uses(tree, index)
        if target_version >= 17:
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == "__last_update":
                    yield (
                        path,
                        node.lineno,
                        "error",
                        "__last_update was removed in Odoo 17; use write_date (or id for stable ordering)",
                    )
        if target_version >= 20:
            for line, level, message in _odoo20_python_issues(tree, index, visitor):
                yield path, line, level, message
        for line, level, message in _removed_sql_field_issues(tree, removed_fields) or ():
            yield path, line, level, message
        for line, message in _dynamic_model_issues(tree):
            yield path, line, "warning", message
        for line, message in _document_relation_issues(
            tree, target_version, document_fields, document_type_domains
        ) or ():
            yield path, line, "warning", message
        for line, message in _persistent_wizard_issues(
            tree, index, modal_models, searched_models
        ):
            yield path, line, "warning", message
        for line, message in _html_field_issues(tree, index):
            yield path, line, "warning", message
        for line, message in _multi_record_self_issues(tree, index):
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
                enterprise = owners <= index.enterprise_modules
                yield (
                    path,
                    node.lineno,
                    "warning" if enterprise or not complete else "error",
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
                enterprise = owners <= index.enterprise_modules
                yield (
                    path,
                    node.lineno,
                    "warning" if enterprise or not complete else "error",
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
                and field not in models.BASE_ATTRIBUTES
                and not field.isupper()
                and not any(field in index.methods.get(m, set()) for m in ancestors)
            ):
                if model in index.abstract:
                    concrete = []
                    for candidate in sorted(index.defined - index.abstract):
                        if model not in index.ancestors(candidate):
                            continue
                        kinds = "/".join(sorted(index.field_types.get((candidate, field), set())))
                        if field in index.fields.get(candidate, set()):
                            concrete.append(candidate + (f" ({kinds})" if kinds else ""))
                    detail = (
                        "; concrete inheritors define it differently: " + ", ".join(concrete)
                        if concrete else ""
                    )
                else:
                    detail = ""
                yield (
                    path,
                    node.lineno,
                    "error",
                    f"Field {model}.{field} does not exist in the indexed target{detail}",
                )
            if target_version >= 17 and field == "__last_update":
                yield (
                    path,
                    node.lineno,
                    "error",
                    "__last_update was removed in Odoo 17; use write_date (or id for stable ordering)",
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
        for node, model, method in visitor.method_calls:
            ancestors = index.ancestors(model)
            if (
                complete
                and ancestors <= index.defined
                and not any(method in index.methods.get(ancestor, set()) for ancestor in ancestors)
                and method not in models.BASE_ATTRIBUTES
                and method not in {"get_param", "set_param", "_file_read"}
            ):
                yield (
                    path,
                    node.lineno,
                    "error",
                    f"Method {model}.{method}() does not exist in the indexed target",
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
                    local_dependencies = {
                        arg.value
                        for decorator in stmt.decorator_list
                        if isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == "depends"
                        for arg in decorator.args
                        if isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                    }
                    inherited_dependencies = set().union(
                        *(
                            index.method_depends.get((ancestor, stmt.name, owner), set())
                            for ancestor in ancestors
                            for owner in index.method_owners.get(
                                (ancestor, stmt.name), set()
                            )
                            if owner not in {module.name, "base"}
                            and owner in closure
                        )
                    )
                    if stmt.name.startswith("_compute_") and inherited_dependencies:
                        missing_dependencies = inherited_dependencies - local_dependencies
                        extra_dependencies = local_dependencies - inherited_dependencies
                        if missing_dependencies or extra_dependencies:
                            differences = []
                            if missing_dependencies:
                                differences.append(
                                    "missing " + ", ".join(sorted(missing_dependencies))
                                )
                            if extra_dependencies:
                                differences.append(
                                    "additional " + ", ".join(sorted(extra_dependencies))
                                )
                            yield (
                                path,
                                stmt.lineno,
                                "warning",
                                f"{model}.{stmt.name} overrides a target compute method with"
                                f" different @api.depends ({'; '.join(differences)}); review"
                                " whether the custom early-return still handles target recomputations",
                            )
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
                    target_signature = _target_method_signature(
                        index, ancestors, stmt.name, closure, module.name
                    )
                    if target_signature:
                        local_signature = models.method_signature(stmt)
                        signature_problem = _signature_problem(
                            local_signature,
                            target_signature,
                            _same_super_calls(stmt),
                        )
                        if signature_problem:
                            yield (
                                path,
                                stmt.lineno,
                                "error" if complete else "warning",
                                f"{model}.{stmt.name} override is incompatible with the indexed target: "
                                f"custom {models.format_signature(local_signature)}, target "
                                f"{models.format_signature(target_signature)}; {signature_problem}",
                            )
                    calls_any_super = any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "super"
                        for node in ast.walk(stmt)
                    )
                    if inherited_owners and not calls_any_super:
                        target_calls = set()
                        target_owners = inherited_owners & closure
                        for ancestor in ancestors:
                            for owner in target_owners:
                                direct = index.method_calls.get(
                                    (ancestor, stmt.name, owner), set()
                                )
                                target_calls.update(direct)
                                for called in direct:
                                    target_calls.update(
                                        index.method_calls.get(
                                            (ancestor, called, owner), set()
                                        )
                                    )
                        hooks = sorted(
                            name
                            for name in target_calls
                            if name.startswith(("_affects_", "_prepare_"))
                            or name.startswith("_get_") and name.endswith("_domain")
                        )
                        if hooks:
                            yield (
                                path,
                                stmt.lineno,
                                "warning",
                                f"{model}.{stmt.name} replaces the target implementation without"
                                f" super(); target extension hooks are available: {', '.join(hooks)}."
                                " Prefer the narrowest hook to preserve future standard behavior",
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
