# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Find where a field of a *known model* is used, in Python and XML files.

Only the places where the model is certain are reported, so renaming them is
safe and warnings about removed fields are not false positives:

Python (ast), in a class whose _name / _inherit is the model M:
  * ``self.f`` and ``rec.f`` where ``rec`` iterates over ``self``;
  * first segment of the paths of ``@api.depends / onchange / constrains``;
  * first segment of ``related=`` of the fields defined in the class;
  * keys of ``self.write({...})`` / ``self.create({...})`` dicts and first
    elements of domain tuples of ``self.search([...])``, and the same on
    ``self.env['M2']`` for the model M2.

XML (lxml):
  * ``<field name="f">`` children of ``<record model="M">``;
  * fields of views (ir.ui.view) of model M, outside sub-views of x2many fields;
  * ``@name='f'`` in the ``expr`` of ``<xpath>`` of inherited views of M.

A field defined by the module itself on M is never reported (the module adds
or re-adds it).
"""

import ast
import re
from dataclasses import dataclass

from lxml import etree

FIELD_DECORATORS = {"depends", "onchange", "constrains", "depends_context"}
RECORD_METHODS_DICT = {"write", "create", "update"}
RECORD_METHODS_DOMAIN = {"search", "search_count", "search_read", "read_group",
                         "_read_group", "filtered_domain", "search_fetch"}


@dataclass(frozen=True)
class Usage:
    model: str
    field: str
    line: int          # 1-based
    start: int         # offset in the text of the field name
    end: int
    context: str       # human readable


class _Positions:
    def __init__(self, text):
        self.lines = text.splitlines(keepends=True)
        self.starts = [0, 0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))

    def offset(self, lineno, col_offset):
        line = self.lines[lineno - 1].encode("utf-8")
        return self.starts[lineno] + len(line[:col_offset].decode("utf-8", "replace"))


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

def _str_list(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _class_models(cls):
    name, inherit = None, []
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            if stmt.targets[0].id == "_name":
                name = (_str_list(stmt.value) or [None])[0]
            elif stmt.targets[0].id == "_inherit":
                inherit = _str_list(stmt.value)
    if name:
        return [name]
    return inherit


def _defined_fields(cls):
    result = set()
    for stmt in cls.body:
        if (
            isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and isinstance(stmt.value.func.value, ast.Name)
            and stmt.value.func.value.id == "fields"
        ):
            result.add(stmt.targets[0].id)
    return result


def _env_model(node):
    """'M' for self.env['M'] / env['M'] / self.env.ref(...) not handled."""
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "env"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    ):
        return node.slice.value
    return None


class _PyVisitor(ast.NodeVisitor):
    def __init__(self, text):
        self.text = text
        self.pos = _Positions(text)
        self.usages = []
        self.defined = {}  # model -> fields defined in this file
        self.models = []
        self.self_names = {"self"}
        self.called = set()

    # -- helpers
    def _add_str_path(self, models, const, context):
        """First segment of 'a.b.c' inside a string constant node."""
        if not (isinstance(const, ast.Constant) and isinstance(const.value, str)):
            return
        value = const.value
        first = re.match(r"[A-Za-z_]\w*", value)
        if not first:
            return
        start = self.pos.offset(const.lineno, const.col_offset)
        raw = self.text[start:self.pos.offset(const.end_lineno, const.end_col_offset)]
        inner = raw.find(value[: len(first.group(0))])
        if inner < 0:
            return
        for model in models:
            self.usages.append(Usage(
                model, first.group(0), const.lineno,
                start + inner, start + inner + len(first.group(0)), context,
            ))

    def _add_attr(self, models, node, context):
        end = self.pos.offset(node.end_lineno, node.end_col_offset)
        for model in models:
            self.usages.append(Usage(model, node.attr, node.end_lineno, end - len(node.attr), end, context))

    def _receiver_models(self, node):
        if isinstance(node, ast.Name) and node.id in self.self_names:
            return self.models
        model = _env_model(node)
        return [model] if model else []

    # -- visitors
    def visit_ClassDef(self, node):
        saved = self.models, self.self_names
        self.models = _class_models(node)
        self.self_names = {"self"}
        for model in self.models:
            self.defined.setdefault(model, set()).update(_defined_fields(node))
        if self.models:
            for stmt in node.body:
                # related='f.g' of the fields defined here
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
                    for kw in stmt.value.keywords:
                        if kw.arg == "related":
                            self._add_str_path(self.models, kw.value, "related=")
        self.generic_visit(node)
        self.models, self.self_names = saved

    def visit_FunctionDef(self, node):
        if self.models:
            for deco in node.decorator_list:
                if (
                    isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in FIELD_DECORATORS
                ):
                    for arg in deco.args:
                        self._add_str_path(self.models, arg, f"@api.{deco.func.attr}")
        saved = set(self.self_names)
        self.generic_visit(node)
        self.self_names = saved

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_For(self, node):
        # for rec in self / self.filtered(...) / self.sorted(...)
        it = node.iter
        while isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) and it.func.attr in (
            "filtered", "sorted", "with_context", "sudo", "with_company"
        ):
            it = it.func.value
        if isinstance(it, ast.Name) and it.id in self.self_names and isinstance(node.target, ast.Name):
            self.self_names.add(node.target.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if (
            self.models and id(node) not in self.called
            and isinstance(node.value, ast.Name)
            and node.value.id in self.self_names
            and isinstance(node.ctx, (ast.Load, ast.Store))
        ):
            self._add_attr(self.models, node, f"{node.value.id}.{node.attr}")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute):
            self.called.add(id(node.func))  # self.write(...) is not a field
            method = node.func.attr
            models = self._receiver_models(node.func.value)
            if models and node.args:
                arg = node.args[0]
                if method in RECORD_METHODS_DICT and isinstance(arg, ast.Dict):
                    for key in arg.keys:
                        self._add_str_path(models, key, f".{method}({{...}})")
                elif method in RECORD_METHODS_DOMAIN and isinstance(arg, ast.List):
                    for elt in arg.elts:
                        if isinstance(elt, ast.Tuple) and elt.elts:
                            self._add_str_path(models, elt.elts[0], f".{method}([...])")
        self.generic_visit(node)


def python_usages(text):
    """(usages, fields defined per model) of a Python file."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], {}
    visitor = _PyVisitor(text)
    visitor.visit(tree)
    return visitor.usages, visitor.defined


# ---------------------------------------------------------------------------
# XML
# ---------------------------------------------------------------------------

XPATH_NAME_RE = re.compile(r"""@name\s*=\s*(["'])(\w+)\1""")


def _attr_span(text, pos, line, tag, attr, value, taken):
    """Offsets of `value` in <tag ... attr="value"> starting on `line`.

    `taken` holds the offsets already used, for several identical tags.
    """
    pattern = re.compile(rf"""<{tag}\b[^>]*?\b{attr}\s*=\s*(["']){re.escape(value)}\1""")
    for match in pattern.finditer(text, pos.starts[line]):
        value_start = match.end() - len(value) - 1
        if value_start not in taken:
            taken.add(value_start)
            return value_start, value_start + len(value)
    return None


def xml_usages(text):
    try:
        root = etree.fromstring(text.encode("utf-8"))
    except etree.XMLSyntaxError:
        return []
    pos = _Positions(text)
    usages = []
    taken = set()

    def add(model, name, node, attr, context):
        span = _attr_span(text, pos, node.sourceline, node.tag, attr, name, taken)
        if span:
            usages.append(Usage(model, name, node.sourceline, span[0], span[1], context))

    for record in root.iter("record"):
        model = record.get("model")
        if not model:
            continue
        for field in record.findall("field"):
            add(model, field.get("name"), field, "name", f"<record model={model}>")
        if model != "ir.ui.view":
            continue
        view_model = record.findtext("field[@name='model']")
        arch = record.find("field[@name='arch']")
        if not view_model or arch is None:
            continue
        for node in arch.iter("field"):
            # skip sub-views of x2many fields (they show another model)
            if any(parent.tag == "field" for parent in node.iterancestors() if parent is not arch):
                continue
            if node.get("name"):
                add(view_model.strip(), node.get("name"), node, "name", f"view of {view_model.strip()}")
        for node in arch.iter("xpath"):
            expr = node.get("expr") or ""
            if "field" not in expr:
                continue
            for match in XPATH_NAME_RE.finditer(expr):
                # only the first @name of the path is a field of the view model
                span_start = pos.starts[node.sourceline]
                tag_end = text.find(">", span_start)
                found = text.find(match.group(0), span_start, tag_end)
                if found >= 0:
                    value_start = found + match.group(0).index(match.group(2))
                    usages.append(Usage(
                        view_model.strip(), match.group(2), node.sourceline,
                        value_start, value_start + len(match.group(2)),
                        f"xpath of a view of {view_model.strip()}",
                    ))
                break
    return usages


def remove_displayed_fields(text, usages, removed):
    """Remove ``<field name="f" .../>`` of views when M.f does not exist anymore.

    Only self-closing elements without ``position`` (a displayed field, not an
    anchor) of the view of model M are removed. Returns (text, removed usages).
    """
    spans = []
    for usage in usages:
        if (usage.model, usage.field) not in removed or not usage.context.startswith("view of"):
            continue
        tag_start = text.rfind("<", 0, usage.start)
        tag_end = text.find(">", usage.start)
        if tag_start < 0 or tag_end < 0:
            continue
        tag = text[tag_start:tag_end + 1]
        if not tag.startswith("<field") or not tag.endswith("/>") or re.search(r"\bposition\s*=", tag):
            continue
        line_start = text.rfind("\n", 0, tag_start) + 1
        line_end = text.find("\n", tag_end)
        line_end = len(text) if line_end < 0 else line_end
        if not text[line_start:tag_start].strip() and not text[tag_end + 1:line_end].strip():
            spans.append((line_start, min(line_end + 1, len(text)), usage))
        else:
            spans.append((tag_start, tag_end + 1, usage))
    done = []
    for start, end, usage in sorted(spans, key=lambda s: s[0], reverse=True):
        text = text[:start] + text[end:]
        done.append(usage)
    return text, done


def apply_renames(text, usages, renames):
    """Rename the usages found in `renames` {(model, old): new}."""
    edits = sorted(
        {(u.start, u.end, renames[(u.model, u.field)]) for u in usages if (u.model, u.field) in renames},
        reverse=True,
    )
    for start, end, new in edits:
        text = text[:start] + new + text[end:]
    return text, len(edits)
