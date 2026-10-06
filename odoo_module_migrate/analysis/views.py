# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Check inherited views and external XML ids against the target Odoo.

1. Anchors of inherited views (``ir.ui.view`` records and QWeb ``<template>``):
   the last step of an xpath (``//button[@name='x']``, ``//t[@t-set='x']``...)
   or an element with ``position`` (``<field name="x" position="...">``) must
   exist in the target view, or in one of the views of its inheritance tree
   that belong to the dependencies of the module. Otherwise the view does not
   install (e.g. the ``type`` column of product.product_product_tree_view in 20.0).
   An anchor without identifying attribute (``<header position="inside">``,
   ``//header``) needs at least an element with this tag (no ``<header>`` in
   product.product_normal_form_view in 20.0). What the view inserts itself
   counts (a later spec may be anchored on it).
2. External XML ids (``ref="sale.xxx"``, ``ref('sale.xxx')``, override
   ``<record id="sale.xxx">``) of Odoo modules must exist in the target Odoo
   (e.g. ``base_address_extended.menu_res_city`` in 20.0).

An anchor / XML id is reported only when it can be found nowhere: no false
positive (some cases may be missed).
"""

import ast
import collections
import csv
import io
import pathlib
import re

from lxml import etree

# attributes that identify an element in an anchor
ANCHOR_ATTRS = ("name", "id", "t-set", "t-call", "t-name", "string", "for", "t-as")
STEP_RE = re.compile(r"""^([\w\-]+|\*)\[@([\w\-]+)\s*=\s*(["'])([^"']*)\3\]$""")
# a step that is a bare tag, possibly with a position ('header', 'group[2]')
TAG_STEP_RE = re.compile(r"^([\w\-]+)(?:\[\d+\])?$")
REF_EVAL_RE = re.compile(r"""\bref\(\s*["']([\w]+\.[\w.]+)["']\s*\)""")
# XML ids created by the ORM / the module loader, not by data files
GENERATED_PREFIXES = ("model_", "field_", "selection__", "module_", "access_", "constraint_")


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
            (module / "__manifest__.py").read_text(encoding="utf-8", errors="replace").lstrip()
        )
    except (ValueError, SyntaxError):
        return {}


def _data_files(module, suffixes=(".xml",)):
    manifest = _manifest(module)
    files = manifest.get("data", []) + manifest.get("demo", [])
    return [module / f for f in files if f.endswith(suffixes) and (module / f).is_file()]


def _qualify(ref, module):
    return ref if "." in ref else f"{module}.{ref}"


def _parse(path):
    try:
        return etree.parse(str(path)).getroot()
    except (etree.XMLSyntaxError, OSError):
        return None


def _views(root, module):
    """(xmlid, inherit xmlid or None, arch element, node to report) of a file."""
    for record in root.iter("record"):
        if record.get("model") != "ir.ui.view" or not record.get("id"):
            continue
        inherit = record.find("field[@name='inherit_id']")
        parent = _qualify(inherit.get("ref"), module) if inherit is not None and inherit.get("ref") else None
        yield (_qualify(record.get("id"), module), parent,
               record.find("field[@name='arch']"), inherit if inherit is not None else record)
    for template in root.iter("template"):
        if not template.get("id"):
            continue
        parent = _qualify(template.get("inherit_id"), module) if template.get("inherit_id") else None
        yield _qualify(template.get("id"), module), parent, template, template


def _keys(arch):
    """(tag, attr, value) of the elements of an arch, plus (*, attr, value)
    and (tag, '', '') for the tag alone."""
    keys = set()
    if arch.tag == "template":
        keys.add(("t", "", ""))  # the arch of a <template> is a <t t-name="...">
    for node in arch.iter():
        if not isinstance(node.tag, str):
            continue
        keys.add((node.tag, "", ""))
        for attr in ANCHOR_ATTRS:
            value = node.get(attr)
            if value:
                keys.add((node.tag, attr, value))
                keys.add(("*", attr, value))
    return keys


def _steps(expr):
    """Simple steps of an xpath: '//page[@name="a"]/field[@name="b"]/list'
    -> [('page', 'name', 'a'), ('field', 'name', 'b')] (other steps skipped)."""
    parts, depth, current = [], 0, ""
    for char in expr:
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if char == "/" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    result = []
    for part in parts:
        match = STEP_RE.match(part.strip())
        if match:
            result.append((match.group(1), match.group(2), match.group(4)))
            continue
        match = TAG_STEP_RE.match(part.strip())
        if match:
            # e.g. //header: Odoo needs such an element in the arch
            result.append((match.group(1), "", ""))
    return result


class ViewIndex:
    def __init__(self):
        self.keys = collections.defaultdict(set)      # view -> (tag, attr, value)
        self.children = collections.defaultdict(set)  # view -> views extending it
        self.parent = {}                              # view -> inherit_id
        self.views = set()
        self.view_modules = collections.defaultdict(set)  # view -> modules defining it
        self.depends = {}                             # module -> depends
        self.xmlids = set()                           # all the XML ids of data files
        self.modules = set()

    def add_module(self, module):
        name = module.name
        self.modules.add(name)
        self.depends[name] = _manifest(module).get("depends", [])
        for path in _data_files(module, (".xml", ".csv")):
            if path.suffix == ".csv":
                self._add_csv(path, name)
                continue
            root = _parse(path)
            if root is None:
                continue
            for node in root.iter("record", "template", "menuitem", "report", "act_window"):
                xid = node.get("id")
                # an XML id is created by its own module (others only update it)
                if xid and ("." not in xid or xid.startswith(name + ".")):
                    self.xmlids.add(_qualify(xid, name))
            for xid, parent, arch, _node in _views(root, name):
                self.views.add(xid)
                self.view_modules[xid].add(name)
                if parent:
                    self.children[parent].add(xid)
                    self.parent[xid] = parent
                if arch is not None:
                    self.keys[xid] |= _keys(arch)

    def _add_csv(self, path, module):
        try:
            rows = csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig", errors="replace")))
            header = next(rows, [])
        except csv.Error:
            return
        if header and header[0] == "id":
            for row in rows:
                if row and row[0]:
                    self.xmlids.add(_qualify(row[0], module))

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

    def complete(self, closure):
        """Whether all the modules of a closure are indexed: only then a module
        is known for sure to be outside the dependencies."""
        return all(name in self.depends for name in closure)

    def unknown_dependencies(self, module):
        """Dependencies (direct or not) of the module absent from the indexed
        addons paths: what they add (views, XML ids, models) is unknown."""
        return sorted(self.closure(module) - set(self.depends))

    def available(self, xid, modules=None, exclude=(), _seen=None):
        """Anchor keys of the view and of the views extending it; only the
        views of `modules` (the dependencies, installed for sure) count."""
        seen = _seen if _seen is not None else set()
        if xid in seen:
            return set()
        seen.add(xid)
        result = set()
        if xid not in exclude and (modules is None or self.view_modules.get(xid, set()) & modules):
            result |= self.keys.get(xid, set())
        for child in self.children.get(xid, ()):
            result |= self.available(child, modules, exclude, seen)
        return result


def _specs(arch):
    """Specs of an inheriting arch, in the order Odoo applies them: the
    children of a <data> are queued after the other specs
    (odoo/tools/template_inheritance.py, apply_inheritance_specs)."""
    queue = [node for node in arch if isinstance(node.tag, str)]
    while queue:
        node = queue.pop(0)
        if node.tag == "data":
            queue += [child for child in node if isinstance(child.tag, str)]
        else:
            yield node


def _anchors(arch):
    """(node, (tag, attr, value), keys added before) of the anchors of an
    inheriting arch. Odoo applies the specs in order: a spec may be anchored
    on an element added by a previous spec of the same view
    (odoo/tools/template_inheritance.py, apply_inheritance_specs)."""
    added = set()
    for node in _specs(arch):
        if node.tag == "xpath":
            # every step of the path must exist (e.g. a removed x2many field in
            # the middle of the path); only the attributes of the index can be
            # checked (no false positive)
            for step in _steps(node.get("expr") or ""):
                if step[1] in ANCHOR_ATTRS or step[1] == "":
                    yield node, step, added
        elif node.get("position"):
            for attr in ANCHOR_ATTRS:
                if node.get(attr):
                    yield node, (node.tag, attr, node.get(attr)), added
                    break
            else:
                # <header position="inside">: Odoo looks for an element with this
                # tag (and the same other attributes): the tag must exist
                yield node, (node.tag, "", ""), added
        if node.get("position") != "attributes":
            for child in node:
                if isinstance(child.tag, str):
                    added = added | _keys(child)


def _describe(key):
    tag, attr, value = key
    return f"{tag}[@{attr}='{value}']" if attr else f"<{tag}>"


def check_module(module, index, reference_modules):
    """Yield (path, line, message) for the anchors and XML ids not found."""
    module = pathlib.Path(module)
    closure = index.closure(module.name)
    # a dependency outside the addons paths may add any anchor, XML id or
    # dependency: then only what must exist in the target Odoo itself is checked
    complete = index.complete(closure)
    for path in _data_files(module):
        root = _parse(path)
        if root is None:
            continue
        for xid, parent, arch, report_node in _views(root, module.name):
            if parent is None or arch is None:
                continue
            if parent not in index.views:
                if parent.split(".")[0] in reference_modules:
                    yield path, report_node.sourceline, (
                        f"parent view {parent} does not exist in the target Odoo"
                    )
                continue
            if not complete:
                continue
            owner = parent.split(".")[0]
            if owner in index.modules and owner not in closure:
                # its anchors cannot be found: the real error is the dependency
                # (installed only if another module happens to install it first)
                yield path, report_node.sourceline, _missing_depends(
                    f"parent view {parent}", owner
                )
                continue
            # the view itself does not count: it holds the anchors
            available = index.available(index.root(parent), closure, exclude={xid})
            for node, key, added in _anchors(arch):
                if key not in available and key not in added:
                    yield path, node.sourceline, (
                        f"{_describe(key)} not found in the view {parent} of the target"
                        f" Odoo (nor in any view of its inheritance tree): the view will"
                        f" not install"
                    )
        yield from _check_xmlids(
            path, root, module.name, index, reference_modules, closure if complete else None
        )


def _missing_depends(what, owner):
    return (
        f"{what} comes from the module '{owner}', which is not in the dependencies of the"
        f" module: add it to 'depends'"
    )


def _check_xmlids(path, root, module_name, index, reference_modules, closure=None):
    seen = set()
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        if node.tag == "field" and node.get("name") == "inherit_id":
            continue  # parent views: reported by the anchors check
        refs = []
        if node.tag in ("record", "template", "menuitem") and "." in (node.get("id") or ""):
            refs.append(node.get("id"))  # override of a record of another module
        for attr in ("ref", "parent", "action", "groups"):
            value = node.get(attr)
            if not value:
                continue
            if attr == "groups":
                refs += [g.lstrip("!").strip() for g in value.split(",") if "." in g]
            elif "." in value:
                refs.append(value)
        refs += REF_EVAL_RE.findall(node.get("eval") or "")
        for ref in refs:
            module, _, local = ref.partition(".")
            if (
                module == module_name or module not in index.modules
                or local.startswith(GENERATED_PREFIXES) or (ref, node.sourceline) in seen
            ):
                continue
            seen.add((ref, node.sourceline))
            if ref not in index.xmlids:
                # only the target Odoo is known for sure (an XML id of another
                # custom module may be created by its code)
                if module in reference_modules:
                    yield path, node.sourceline, f"XML id {ref} does not exist in the target Odoo"
            elif closure is not None and module not in closure:
                # works only if another module happens to install it first
                yield path, node.sourceline, _missing_depends(f"XML id {ref}", module)
