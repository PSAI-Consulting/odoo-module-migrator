# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""``odoo.registry()`` was removed in 19.0.

Sources:
- 18.0 odoo/__init__.py: ``def registry(database_name=None)`` warns
  ``DeprecationWarning("Use directly odoo.modules.registry.Registry")`` and
  returns ``modules.registry.Registry(database_name)`` (``database_name``
  defaults to ``threading.current_thread().dbname``);
- odoo 8b3480b39740 '[IMP] core: PEP420 native namespace' (19.0) deletes
  odoo/__init__.py, so ``from odoo import registry`` raises ImportError and
  ``odoo.registry`` AttributeError;
- ``odoo.modules.registry.Registry`` exists from 17.0 to 20.0
  (20.0 odoo/modules/registry/__init__.py re-exports odoo.orm.registry).

    from odoo import api, registry     ->   from odoo import api
                                            from odoo.modules.registry import Registry
    registry(dbname)                   ->   Registry(dbname)
    odoo.registry(dbname)              ->   Registry(dbname)   (+ import)

Done in 18 -> 19 (the removal): the code still works in 18.0, and a migration
starting from 18.0 code is also covered. Only the module level binding of
``registry`` imported from ``odoo`` is followed: a parameter, a local variable
or ``self.env.registry`` are never touched. A call without argument (the
thread database), or any other use of the name, is reported and the file is
left as is for that name.
"""

import ast

REGISTRY_MODULES = ("odoo.modules.registry", "odoo.orm.registry")
IMPORT_LINE = "from odoo.modules.registry import Registry"
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _offsets(text):
    lines = text.splitlines(keepends=True)
    starts = [0, 0]
    for line in lines:
        starts.append(starts[-1] + len(line))

    def offset(lineno, col):
        return starts[lineno] + len(lines[lineno - 1].encode("utf-8")[:col].decode("utf-8", "replace"))

    return offset


def _bound_names(nodes):
    """Names bound by these statements, without entering nested scopes."""
    bound, declared_global = set(), set()
    todo = list(nodes)
    while todo:
        node = todo.pop()
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            # decorators, defaults, bases: evaluated in this scope
            todo += node.decorator_list + getattr(node, "bases", []) + getattr(node, "keywords", [])
            if not isinstance(node, ast.ClassDef):
                todo += node.args.defaults + [d for d in node.args.kw_defaults if d]
            continue
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            if isinstance(node, ast.Global):
                declared_global.update(node.names)
        elif isinstance(node, (ast.Lambda,) + COMPREHENSIONS):
            continue
        elif hasattr(ast, "MatchAs") and isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            bound.add(node.name)
        todo += list(ast.iter_child_nodes(node))
    return bound - declared_global


def _args(args):
    names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    names += [a.arg for a in (args.vararg, args.kwarg) if a]
    return set(names)


def _global_loads(tree, names):
    """Load ``ast.Name`` nodes of ``names`` that refer to the module level binding."""
    found = []

    def visit(node, shadowed):
        if isinstance(node, ast.Name):
            if node.id in names and node.id not in shadowed and isinstance(node.ctx, ast.Load):
                found.append(node)
            return
        if isinstance(node, SCOPES):
            outer = (node.args.defaults + [d for d in node.args.kw_defaults if d])
            if not isinstance(node, ast.Lambda):
                outer += node.decorator_list
                if node.returns:
                    outer.append(node.returns)
            for child in outer:
                visit(child, shadowed)
            body = node.body if isinstance(node.body, list) else [node.body]
            declared_global = {
                n for stmt in body for sub in ast.walk(stmt)
                if isinstance(sub, ast.Global) for n in sub.names
            }
            local = (_args(node.args) | _bound_names(body)) - declared_global
            inner = (shadowed | local) - declared_global
            for child in body:
                visit(child, inner)
            return
        if isinstance(node, ast.ClassDef):
            for child in node.decorator_list + node.bases + node.keywords:
                visit(child, shadowed)
            class_local = _bound_names(node.body)
            for child in node.body:
                # methods do not see the class scope
                visit(child, shadowed if isinstance(child, SCOPES) else shadowed | class_local)
            return
        if isinstance(node, COMPREHENSIONS):
            targets = {
                n.id for gen in node.generators for n in ast.walk(gen.target) if isinstance(n, ast.Name)
            }
            visit(node.generators[0].iter, shadowed)
            inner = shadowed | targets
            for gen in node.generators:
                for child in [gen.target] + gen.ifs + ([gen.iter] if gen is not node.generators[0] else []):
                    visit(child, inner)
            for child in ([node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]):
                visit(child, inner)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, shadowed)

    for stmt in tree.body:
        visit(stmt, set())
    return found


def _call_argument(call, text, offset):
    """Source of the database name argument, or None if not a simple call."""
    if len(call.args) == 1 and not call.keywords and not isinstance(call.args[0], ast.Starred):
        return True
    if not call.args and len(call.keywords) == 1 and call.keywords[0].arg == "database_name":
        value = call.keywords[0].value
        return text[offset(value.lineno, value.col_offset):offset(value.end_lineno, value.end_col_offset)]
    return None


def _rewrite(text):
    """Return (new text, [(line, what)] left as is)."""
    tree = ast.parse(text)
    offset = _offsets(text)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    reported = []

    imports = [
        node for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "odoo" and node.level == 0
        and any(a.name == "registry" for a in node.names)
    ]
    for node in ast.walk(tree):
        if (isinstance(node, ast.ImportFrom) and node.module == "odoo" and node.level == 0
                and node not in imports and any(a.name == "registry" for a in node.names)):
            reported.append((node.lineno, "from odoo import registry (not at module level)"))
    local = {a.asname or a.name for node in imports for a in node.names if a.name == "registry"}
    odoo_bound = any(
        isinstance(node, ast.Import) and any(a.name.split(".")[0] == "odoo" and not a.asname for a in node.names)
        for node in tree.body
    )
    module_bound = _bound_names([n for n in tree.body if n not in imports])
    rebound = local & module_bound
    if rebound:
        # registry = ... at module level: which binding is used is not followed
        reported += [(node.lineno, "registry rebound at module level") for node in imports]
        local = set()

    # Registry must be free, or already imported from odoo
    registry_imported = any(
        isinstance(node, ast.ImportFrom) and node.module in REGISTRY_MODULES
        and any(a.name == "Registry" and not a.asname for a in node.names)
        for node in tree.body
    )
    other_registry = any(
        (isinstance(n, ast.Name) and n.id == "Registry" and not isinstance(n.ctx, ast.Load))
        or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == "Registry")
        or (isinstance(n, ast.arg) and n.arg == "Registry")
        or (isinstance(n, (ast.Import, ast.ImportFrom)) and any(
            (a.asname or a.name) == "Registry"
            and not (isinstance(n, ast.ImportFrom) and n.module in REGISTRY_MODULES and a.name == "Registry")
            for a in n.names))
        for n in ast.walk(tree)
    )

    edits = []  # (start, end, new)
    names = local | ({"odoo"} if odoo_bound else set())
    by_name, attr_edits = {}, []
    for name_node in (_global_loads(tree, names) if names else []):
        if name_node.id == "odoo":
            attr = parents.get(name_node)
            if not (isinstance(attr, ast.Attribute) and attr.attr == "registry" and attr.value is name_node):
                continue
            target, label = attr, "odoo.registry"
        else:
            target, label = name_node, name_node.id
        call = parents.get(target)
        argument = (
            _call_argument(call, text, offset)
            if isinstance(call, ast.Call) and call.func is target else None
        )
        if argument is None:
            by_name.setdefault(name_node.id, []).append((target.lineno, label, None))
            continue
        if argument is True:
            edit = (offset(target.lineno, target.col_offset),
                    offset(target.end_lineno, target.end_col_offset), "Registry")
        else:
            edit = (offset(call.lineno, call.col_offset),
                    offset(call.end_lineno, call.end_col_offset), "Registry(%s)" % argument)
        by_name.setdefault(name_node.id, []).append((target.lineno, label, edit))

    if other_registry and by_name:
        return text, reported + [
            (line, "%s (the name Registry is already used in the file)" % label)
            for refs in by_name.values() for line, label, _e in refs
        ]
    converted = False
    for name, refs in by_name.items():
        left = [(line, label) for line, label, edit in refs if edit is None]
        reported += left
        if name != "odoo" and left:
            # the import has to stay for the other uses: nothing changed for this name
            continue
        edits += [edit for _l, _label, edit in refs if edit]
        converted |= any(edit for _l, _label, edit in refs)
    keep_imported = rebound | {name for name in local if any(e is None for _l, _lb, e in by_name.get(name, []))}

    need_import = converted and not registry_imported
    for node in imports:
        kept = [a for a in node.names if not (a.name == "registry" and (a.asname or a.name) not in keep_imported)]
        if len(kept) == len(node.names):
            continue
        start = offset(node.lineno, node.col_offset)
        end = offset(node.end_lineno, node.end_col_offset)
        lines = []
        if kept:
            lines.append("from odoo import %s" % ", ".join(
                a.name + (" as %s" % a.asname if a.asname else "") for a in kept))
        if need_import:
            lines.append(IMPORT_LINE)
            need_import = False
        edits.append((start, end, "\n".join(lines)))
    if need_import:
        # odoo.registry(...) only: after the first ``import odoo``
        node = next(
            n for n in tree.body
            if isinstance(n, ast.Import) and any(a.name.split(".")[0] == "odoo" and not a.asname for a in n.names)
        )
        # at the end of its line (after a comment), not of the statement
        end = text.find("\n", offset(node.end_lineno, node.end_col_offset))
        end = len(text) if end < 0 else end
        edits.append((end, end, "\n" + IMPORT_LINE))

    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
        if not new:
            line_start = text.rfind("\n", 0, start) + 1
            line_end = text.find("\n", start)
            line_end = len(text) if line_end < 0 else line_end
            if text[line_start:line_end].strip() == "":
                text = text[:line_start] + text[line_end + 1:]
    return text, sorted(set(reported))


def migrate_odoo_registry(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py",)):
        text = tools._read_content(path)
        if "registry" not in text or "odoo" not in text:
            continue
        try:
            new, reported = _rewrite(text)
        except SyntaxError:
            continue
        if new != text:
            tools._write_content(path, new)
            logger.info("[19] odoo.registry(db) replaced by Registry(db) (odoo.modules.registry) in %s" % path)
        for line, what in reported:
            logger.error(
                "[19] %s: odoo.registry was removed (odoo 8b3480b39740 '[IMP] core: PEP420 native"
                " namespace'): use odoo.modules.registry.Registry(dbname) (without argument, the"
                " database was threading.current_thread().dbname). File %s:%s" % (what, path, line)
            )
