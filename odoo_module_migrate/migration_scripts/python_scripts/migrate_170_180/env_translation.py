"""Use the explicit environment translator inside implicit Python scopes.

The global ``_()`` translator finds the language from its caller's locals. A
generator expression, comprehension or lambda has its own frame, so an Odoo
model method's ``self`` is not a local there. Since Odoo 18, ``self.env._()``
passes the language explicitly. Only these nested expression scopes are
rewritten; ordinary method calls and non-model classes remain untouched.
"""

import ast

from odoo_module_migrate.analysis import fields


NESTED_SCOPES = (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp, ast.Lambda)


def _positions(text):
    return fields._Positions(text)


def _model_class(node):
    return bool(fields._class_models(node))


def _self_method(node):
    args = node.args.posonlyargs + node.args.args
    if not args or args[0].arg != "self":
        return False
    all_args = args + node.args.kwonlyargs
    if node.args.vararg:
        all_args.append(node.args.vararg)
    if node.args.kwarg:
        all_args.append(node.args.kwarg)
    if any(arg.arg == "_" for arg in all_args):
        return False
    # A local binding named '_' is application code, not the imported Odoo
    # translator. Be conservative and leave the whole method unchanged.
    return not any(
        isinstance(name, ast.Name)
        and name.id == "_"
        and isinstance(name.ctx, (ast.Store, ast.Del))
        for name in ast.walk(node)
    )


def _shadowed_self(scope):
    if isinstance(scope, ast.Lambda):
        return "self" in {
            arg.arg
            for arg in (
                scope.args.posonlyargs
                + scope.args.args
                + scope.args.kwonlyargs
            )
        }
    return any(
        isinstance(name, ast.Name)
        and isinstance(name.ctx, ast.Store)
        and name.id == "self"
        for generator in scope.generators
        for name in ast.walk(generator.target)
    )


def _edits(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    imported = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "odoo"
        and any(alias.name == "_" for alias in node.names)
        for node in tree.body
    )
    if not imported:
        return []
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    positions = _positions(text)
    edits = []
    for call in ast.walk(tree):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_"
        ):
            continue
        current = call
        nested = []
        method = model = None
        while current in parents:
            current = parents[current]
            if isinstance(current, NESTED_SCOPES):
                nested.append(current)
            elif isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method = current
                break
        if not method or not nested or not _self_method(method):
            continue
        current = method
        while current in parents:
            current = parents[current]
            if isinstance(current, ast.ClassDef):
                model = current
                break
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                break
        if not model or not _model_class(model) or any(_shadowed_self(s) for s in nested):
            continue
        start = positions.offset(call.func.lineno, call.func.col_offset)
        end = positions.offset(call.func.end_lineno, call.func.end_col_offset)
        edits.append((start, end, call.lineno))
    return edits


def migrate_env_translation(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py",)):
        text = tools._read_content(path)
        edits = _edits(text)
        if not edits:
            continue
        for start, end, _line in sorted(edits, reverse=True):
            text = text[:start] + "self.env._" + text[end:]
        tools._write_content(path, text)
        for _start, _end, line in edits:
            logger.info(
                "[18] Replaced _() with self.env._() inside an implicit Python"
                " scope so the translation language is explicit. File %s:%s",
                path,
                line,
            )
