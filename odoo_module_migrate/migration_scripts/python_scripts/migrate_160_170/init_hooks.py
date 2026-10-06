# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Init hooks receive ``env`` since 17.0.

Source: odoo commit b4a7996e9676 "[IMP] base, *: change the API of init hooks
to pass env" (17.0 odoo/modules/loading.py: ``getattr(py_module, pre_init)(env)``,
``post_init(env)``, ``uninstall_hook(env)``; 16.0: ``pre_init(cr)``,
``post_init(cr, registry)``, ``uninstall_hook(cr, registry)``).

    def post_init_hook(cr, registry):          def post_init_hook(env):
        env = api.Environment(cr, SUPERUSER_ID, {})   ->      env["x"]...
        env["x"]...

The hooks are the functions named by the manifest. ``env = api.Environment(cr,
SUPERUSER_ID, {})`` is dropped; when ``cr`` is still used, ``cr = env.cr`` is
added. A hook using ``registry`` (or another argument) is reported, not changed.
``with api.Environment.manage():`` is dropped first (see environment_manage.py).
``SUPERUSER_ID`` / ``api`` imported from odoo and no longer used are dropped.
"""

import ast

from .environment_manage import _rewrite as _drop_environment_manage

HOOKS = ("pre_init_hook", "post_init_hook", "uninstall_hook")


def _offsets(text):
    starts = [0, 0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    lines = text.splitlines(keepends=True)

    def offset(lineno, col):
        return starts[lineno] + len(lines[lineno - 1].encode("utf-8")[:col].decode("utf-8", "replace"))

    return offset


def _names(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _is_superuser_env(stmt, cr_name):
    """env = api.Environment(cr, SUPERUSER_ID, {})"""
    if not (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
        and stmt.targets[0].id == "env"
        and isinstance(stmt.value, ast.Call)
        and not stmt.value.keywords
        and len(stmt.value.args) == 3
    ):
        return False
    func, (cr, uid, context) = stmt.value.func, stmt.value.args
    return (
        ast.unparse(func) in ("api.Environment", "Environment")
        and isinstance(cr, ast.Name) and cr.id == cr_name
        and ast.unparse(uid) in ("SUPERUSER_ID", "odoo.SUPERUSER_ID")
        and (isinstance(context, ast.Dict) and not context.keys or ast.unparse(context) == "dict()")
    )


def _hook_edits(func, offset, text):
    """(edits, error) for one hook function."""
    args = func.args
    positional = args.posonlyargs + args.args
    if [a.arg for a in positional] == ["env"] and not args.vararg and not args.kwarg:
        return [], None  # already migrated
    if not positional or args.vararg or args.kwarg or args.kwonlyargs:
        return [], "unexpected signature"
    cr_name = positional[0].arg
    # arguments after cr must be unused (registry, vals=None...)
    used = {a.arg for a in positional[1:]} & _names(ast.Module(body=func.body, type_ignores=[]))
    if used:
        return [], "uses %s" % ", ".join(sorted(used))
    edits = []
    body = func.body
    removed = [stmt for stmt in body if _is_superuser_env(stmt, cr_name)]
    kept = [stmt for stmt in body if stmt not in removed]
    if not kept:
        return [], "empty hook"
    for stmt in removed:
        start = offset(stmt.lineno, 0)
        end = offset(stmt.end_lineno + 1, 0) if stmt.end_lineno < len(text.splitlines()) else len(text)
        edits.append((start, end, ""))
    if cr_name in _names(ast.Module(body=kept, type_ignores=[])):
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and len(body) > 1
        ):
            first = body[1]
        indent = " " * first.col_offset
        position = offset(first.lineno, 0)
        edits.append((position, position, "%s%s = env.cr\n" % (indent, cr_name)))
    start = offset(positional[0].lineno, positional[0].col_offset)
    last = args.defaults[-1] if args.defaults else positional[-1]
    end = offset(last.end_lineno, last.end_col_offset)
    edits.append((start, end, "env"))
    return edits, None


def _drop_unused_odoo_imports(text):
    tree = ast.parse(text)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    offset = _offsets(text)
    for node in sorted(tree.body, key=lambda n: -n.lineno):
        if not (isinstance(node, ast.ImportFrom) and node.module == "odoo" and not node.level):
            continue
        names = [
            a for a in node.names
            if not (a.name in ("SUPERUSER_ID", "api") and (a.asname or a.name) not in used)
        ]
        if len(names) == len(node.names):
            continue
        start = offset(node.lineno, node.col_offset)
        end = offset(node.end_lineno, node.end_col_offset)
        if names:
            new = "from odoo import %s" % ", ".join(
                a.name + (" as %s" % a.asname if a.asname else "") for a in names
            )
            text = text[:start] + new + text[end:]
        else:
            line_end = text.find("\n", end)
            text = text[:start] + text[line_end + 1 if line_end >= 0 else end:]
    return text


def _rewrite(text, hooks):
    """Return (new_text, [(hook, line, error)])."""
    original = text
    # env = api.Environment(...) is often in a `with api.Environment.manage():`
    text = _drop_environment_manage(text)[0]
    tree = ast.parse(text)
    offset = _offsets(text)
    edits, errors = [], []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in hooks:
            func_edits, error = _hook_edits(node, offset, text)
            if error:
                errors.append((node.name, node.lineno, error))
            edits += func_edits
    for start, end, new in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        text = text[:start] + new + text[end:]
    if text == original:
        return text, errors
    return _drop_unused_odoo_imports(text), errors


def migrate_init_hooks(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    manifest_path = kwargs.get("manifest_path")
    if not manifest_path:
        return
    try:
        manifest = ast.literal_eval(tools._read_content(manifest_path))
    except (ValueError, SyntaxError):
        return
    hooks = {manifest[key] for key in HOOKS if isinstance(manifest.get(key), str) and manifest[key]}
    if not hooks:
        return
    for path in tools.get_files(kwargs["module_path"], (".py",)):
        text = tools._read_content(path)
        if not any("def %s(" % hook in text for hook in hooks):
            continue
        try:
            new_text, errors = _rewrite(text, hooks)
        except SyntaxError:
            continue
        if new_text != text:
            tools._write_content(path, new_text)
            logger.info("[17] init hooks now receive env (odoo b4a7996e9676) in %s" % path)
        for hook, line, error in errors:
            logger.error(
                "[17] %s must take env since 17.0 (odoo b4a7996e9676), not changed (%s). File %s:%s"
                % (hook, error, path, line)
            )
