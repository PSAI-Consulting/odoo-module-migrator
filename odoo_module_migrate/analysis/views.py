# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Check the anchors of inherited views against the target Odoo views.

An inherited view anchored on ``//field[@name='x']`` (or ``<field name="x"
position="...">``) fails to install when the parent view of the target Odoo
does not contain the field ``x`` anymore (e.g. the ``type`` column of
product.product_product_tree_view in 20.0).

The index gathers, for each view xmlid, the field names of its arch and of all
the views extending it (any module): an anchor is reported only when it can be
found nowhere, so the check gives no false positive (it may miss cases).
"""

import ast
import collections
import pathlib
import re

from lxml import etree

FIELD_ANCHOR_RE = re.compile(r"""field\[@name=(["'])(\w+)\1\]""")


def _module_dirs(paths):
    for base in paths:
        base = pathlib.Path(base)
        if not base.is_dir():
            continue
        for manifest in base.glob("*/__manifest__.py"):
            yield manifest.parent


def _manifest(module):
    try:
        return ast.literal_eval(
            (module / "__manifest__.py").read_text(encoding="utf-8", errors="replace")
        )
    except (ValueError, SyntaxError):
        return {}


def _data_files(module):
    manifest = _manifest(module)
    files = manifest.get("data", []) + manifest.get("demo", [])
    return [module / f for f in files if f.endswith(".xml") and (module / f).is_file()]


def _qualify(ref, module):
    return ref if "." in ref else f"{module}.{ref}"


class ViewIndex:
    def __init__(self):
        self.fields = collections.defaultdict(set)    # view -> field names
        self.children = collections.defaultdict(set)  # view -> views extending it
        self.parent = {}                              # view -> inherit_id
        self.views = set()
        self.view_modules = collections.defaultdict(set)  # view -> modules defining it
        self.depends = {}                             # module -> depends

    def add_module(self, module):
        name = module.name
        self.depends[name] = _manifest(module).get("depends", [])
        for path in _data_files(module):
            try:
                root = etree.parse(str(path)).getroot()
            except etree.XMLSyntaxError:
                continue
            for record in root.iter("record"):
                if record.get("model") != "ir.ui.view" or not record.get("id"):
                    continue
                xid = _qualify(record.get("id"), name)
                self.views.add(xid)
                self.view_modules[xid].add(name)
                inherit = record.find("field[@name='inherit_id']")
                if inherit is not None and inherit.get("ref"):
                    self.children[_qualify(inherit.get("ref"), name)].add(xid)
                    self.parent[xid] = _qualify(inherit.get("ref"), name)
                arch = record.find("field[@name='arch']")
                if arch is not None:
                    self.fields[xid].update(
                        node.get("name") for node in arch.iter("field") if node.get("name")
                    )

    @classmethod
    def build(cls, paths):
        index = cls()
        for module in _module_dirs(paths):
            index.add_module(module)
        return index

    def root(self, xid):
        """The root view: xpaths are applied on the whole inherited arch."""
        seen = set()
        while xid in self.parent and xid not in seen:
            seen.add(xid)
            xid = self.parent[xid]
        return xid

    def closure(self, module):
        """The module and all its dependencies (base included)."""
        result, todo = set(), [module, "base"]
        while todo:
            name = todo.pop()
            if name not in result:
                result.add(name)
                todo.extend(self.depends.get(name, ()))
        return result

    def all_fields(self, xid, modules=None, exclude=(), _seen=None):
        """Fields of the view and of the views extending it; only the views of
        `modules` (the dependencies, which are installed for sure) count."""
        seen = _seen if _seen is not None else set()
        if xid in seen:
            return set()
        seen.add(xid)
        result = set()
        if xid not in exclude and (modules is None or self.view_modules.get(xid, set()) & modules):
            result |= self.fields.get(xid, set())
        for child in self.children.get(xid, ()):
            result |= self.all_fields(child, modules, exclude, seen)
        return result


def check_module(module, index, reference_modules):
    """Yield (path, line, message) for the anchors not found in the parent."""
    module = pathlib.Path(module)
    for path in _data_files(module):
        try:
            root = etree.parse(str(path)).getroot()
        except etree.XMLSyntaxError:
            continue
        for record in root.iter("record"):
            if record.get("model") != "ir.ui.view":
                continue
            inherit = record.find("field[@name='inherit_id']")
            arch = record.find("field[@name='arch']")
            if inherit is None or arch is None or not inherit.get("ref"):
                continue
            parent = _qualify(inherit.get("ref"), module.name)
            if parent not in index.views:
                if parent.split(".")[0] in reference_modules:
                    yield path, inherit.sourceline, (
                        f"parent view {parent} does not exist in the target Odoo"
                    )
                continue
            # the view itself does not count: it holds the anchors
            xid = _qualify(record.get("id") or "", module.name)
            available = index.all_fields(
                index.root(parent), index.closure(module.name), exclude={xid}
            )
            anchors = []
            for node in arch:
                if not isinstance(node.tag, str):
                    continue
                if node.tag == "xpath":
                    # only the last step of the path must be in the view
                    found = FIELD_ANCHOR_RE.findall(node.get("expr") or "")
                    if found:
                        anchors.append((node, found[-1][1]))
                elif node.tag == "field" and node.get("name"):
                    anchors.append((node, node.get("name")))
            for node, name in anchors:
                if name not in available:
                    yield path, node.sourceline, (
                        f"field '{name}' not found in the view {parent} of the target"
                        f" Odoo (nor in any view of its inheritance tree): the view will"
                        f" not install"
                    )
