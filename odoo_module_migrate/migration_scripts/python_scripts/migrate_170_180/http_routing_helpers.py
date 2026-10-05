# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""http_routing helpers became ir.http class methods in 18.0.

Source: odoo commit 25abac896f53 "[IMP] base: move slug on ir.http to remove
wrong import" (18.0: odoo/addons/base/models/ir_http.py _slugify / _slugify_one,
addons/http_routing/models/ir_http.py _slug, _unslug, _url_for...).

    from odoo.addons.http_routing.models.ir_http import slugify
    slugify(name)  ->  self.env['ir.http']._slugify(name)

The call is rewritten only inside a method whose first argument is ``self``
(so ``self.env`` exists); otherwise the import is kept and an error is logged.
"""

import ast

HELPERS = {
    "slugify": "_slugify",
    "slugify_one": "_slugify_one",
    "slug": "_slug",
    "unslug": "_unslug",
    "unslug_url": "_unslug_url",
    "url_lang": "_url_lang",
    "url_for": "_url_for",
    "is_multilang_url": "_is_multilang_url",
}
MODULE = "odoo.addons.http_routing.models.ir_http"


def _offsets(text):
    starts = [0, 0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    lines = text.splitlines(keepends=True)

    def offset(lineno, col):
        return starts[lineno] + len(lines[lineno - 1].encode("utf-8")[:col].decode("utf-8", "replace"))

    return offset


def _rewrite(text):
    """Return (new_text, unresolved call lines)."""
    tree = ast.parse(text)
    imports = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == MODULE
        and any(alias.name in HELPERS for alias in node.names)
    ]
    if not imports:
        return text, []
    local = {
        alias.asname or alias.name: alias.name
        for node in imports for alias in node.names if alias.name in HELPERS
    }
    offset = _offsets(text)
    edits, unresolved = [], []

    def visit(node, in_self_method):
        for child in ast.iter_child_nodes(node):
            child_self = in_self_method
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = child.args.posonlyargs + child.args.args
                child_self = bool(args) and args[0].arg == "self"
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in local:
                if in_self_method:
                    start = offset(child.func.lineno, child.func.col_offset)
                    end = offset(child.func.end_lineno, child.func.end_col_offset)
                    edits.append((start, end, "self.env['ir.http'].%s" % HELPERS[local[child.func.id]]))
                else:
                    unresolved.append(child.lineno)
            visit(child, child_self)

    visit(tree, False)
    # names still used somewhere else (not as a call): keep the import
    used_elsewhere = {
        n.id for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id in local
        and not any(start <= offset(n.lineno, n.col_offset) < end for start, end, _ in edits)
    }
    keep = {name for name in local if name in used_elsewhere}
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    # rewrite the import statements on the edited text (re-parsed)
    for node in sorted(ast.parse(text).body, key=lambda n: -n.lineno):
        if not (isinstance(node, ast.ImportFrom) and node.module == MODULE):
            continue
        names = [a for a in node.names if not (a.name in HELPERS and (a.asname or a.name) not in keep)]
        offset = _offsets(text)
        start = offset(node.lineno, node.col_offset)
        end = offset(node.end_lineno, node.end_col_offset)
        if names:
            new = "from %s import %s" % (MODULE, ", ".join(
                a.name + (" as %s" % a.asname if a.asname else "") for a in names
            ))
        else:
            new = ""
        text = text[:start] + new + text[end:]
        if not new:
            text = _drop_empty_line(text, start)
    return text, unresolved


def _drop_empty_line(text, pos):
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    if line_end < 0:
        line_end = len(text)
    if text[line_start:line_end].strip() == "":
        return text[:line_start] + text[line_end + 1:]
    return text


def migrate_http_routing_helpers(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py",)):
        text = tools._read_content(path)
        if MODULE not in text:
            continue
        try:
            new_text, unresolved = _rewrite(text)
        except SyntaxError:
            continue
        if new_text != text:
            tools._write_content(path, new_text)
            logger.info("[18] http_routing helpers replaced by ir.http methods in %s" % path)
        for line in unresolved:
            logger.error(
                "[18] slug/slugify... are ir.http methods since 18.0 (odoo 25abac896f53):"
                " call env['ir.http']._slugify(...) etc. File %s:%s" % (path, line)
            )
