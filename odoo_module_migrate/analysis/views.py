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
import copy

from lxml import etree
from functools import lru_cache
from .cache import cached_summary

# attributes that identify an element in an anchor
ANCHOR_ATTRS = ("name", "id", "t-set", "t-call", "t-name", "string", "for", "t-as")
STEP_RE = re.compile(r"""^([\w\-]+|\*)\[@([\w\-]+)\s*=\s*(["'])([^"']*)\3\]$""")
# a step that is a bare tag, possibly with a position ('header', 'group[2]')
TAG_STEP_RE = re.compile(r"^([\w\-]+)(?:\[\d+\])?$")
REF_EVAL_RE = re.compile(r"""\bref\(\s*["']([\w]+\.[\w.]+)["']\s*\)""")
# XML ids created by the ORM / the module loader, not by data files
GENERATED_PREFIXES = ("model_", "field_", "selection__", "module_", "access_", "constraint_")


def _module_dirs(paths):
    # Last path wins (dry-run copies override the original context module).
    modules = {}
    for base in dict.fromkeys(pathlib.Path(p).resolve() for p in paths):
        base = pathlib.Path(base)
        if not base.is_dir():
            continue
        for manifest in base.glob("*/__manifest__.py"):
            modules[manifest.parent.name] = manifest.parent
    yield from modules.values()


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
        stat = path.stat()
        return _parse_cached(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    except (etree.XMLSyntaxError, OSError):
        return None


@lru_cache(maxsize=4096)
def _parse_cached(path, modified, size):
    # Indexing and checking read the same XML files; callers never mutate this tree.
    return etree.parse(path).getroot()


def check_duplicate_fields(module, index):
    """Review-only warning: repeated fields are legal and sometimes intended."""
    for path in _data_files(module):
        root = _parse(path)
        if root is None:
            continue
        for xid, parent, arch, _ in _views(root, module.name):
            if not parent or arch is None:
                continue
            # Only dependencies; sibling views of this module cannot establish
            # that a field is already present in the standard target.
            combined = index.combined(parent, index.closure(module.name) - {module.name}, xid)
            if combined is None:
                continue
            for spec in _specs(arch):
                if spec.get("position", "inside") not in {"before", "after", "inside"}:
                    continue
                try:
                    anchors = _locate(combined, spec)
                except etree.XPathError:
                    continue
                for child in spec:
                    for field in child.iter("field"):
                        name = field.get("name")
                        if not name or field.get("position"):
                            continue
                        matches = [n for n in combined.iter("field") if n.get("name") == name]
                        if not matches:
                            continue
                        # Limit to a common named container when one is supplied.
                        containers = [(n.tag, n.get("name")) for n in field.iterancestors()
                                      if n is not spec and n.get("name") and n.tag in {"group", "div", "page"}]
                        if anchors:
                            if not containers:
                                containers = [(n.tag, n.get("name")) for n in anchors[0].iterancestors()
                                              if n.get("name") and n.tag in {"group", "div", "page"}]
                            if not containers or not any(any((a.tag, a.get("name")) in containers for a in n.iterancestors()) for n in matches):
                                continue
                        yield path, field.sourceline, f"Field {name} is already displayed by target view {parent}; review a possibly redundant block (intentional duplicates are valid)"


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


def _view_summary(path, module):
    result = {"xmlids": [], "precisions": [], "views": []}
    root = _parse(path)
    if root is None:
        return result
    for record in root.iter("record"):
        if record.get("model") == "decimal.precision":
            name = record.find("field[@name='name']")
            if name is not None and name.text:
                result["precisions"].append(name.text)
    for node in root.iter("record", "template", "menuitem", "report", "act_window"):
        xid = node.get("id")
        if xid and ("." not in xid or xid.startswith(module + ".")):
            result["xmlids"].append(_qualify(xid, module))
    for xid, parent, arch, _ in _views(root, module):
        priority = 16
        if arch is not None and arch.getparent() is not None:
            value = arch.getparent().find("field[@name='priority']")
            if value is not None:
                try:
                    priority = int(value.get("eval") or value.text)
                except (TypeError, ValueError):
                    pass
        result["views"].append(dict(xid=xid, parent=parent, priority=priority,
                                    arch=etree.tostring(arch, encoding="unicode", with_tail=False) if arch is not None else None,
                                    keys=sorted(_keys(arch)) if arch is not None else []))
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
        self.arches = {}
        self.priorities = {}
        self.precisions = set()
        self.order = {}
        self.incomplete_combinations = set()

    def add_module(self, module):
        name = module.name
        self.modules.add(name)
        self.depends[name] = _manifest(module).get("depends", [])
        for path in _data_files(module, (".xml", ".csv")):
            if path.suffix == ".csv":
                self._add_csv(path, name)
                continue
            summary = cached_summary(path, lambda p: _view_summary(p, name))
            self.precisions.update(summary["precisions"])
            self.xmlids.update(summary["xmlids"])
            for item in summary["views"]:
                xid, parent = item["xid"], item["parent"]
                self.views.add(xid)
                self.view_modules[xid].add(name)
                if parent:
                    self.children[parent].add(xid)
                    self.parent[xid] = parent
                if item["arch"] is not None:
                    self.keys[xid].update(tuple(key) for key in item["keys"])
                    self.arches[xid] = etree.fromstring(item["arch"].encode())
                    self.order.setdefault(xid, len(self.order))
                    self.priorities[xid] = item["priority"]

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

    def combined(self, parent, modules, exclude):
        root = self.root(parent)
        arch = self.arches.get(root)
        if arch is None:
            return None
        if arch.tag == "template":
            result = etree.Element("t")
            result.extend(copy.deepcopy(list(arch)))
        elif len(arch) == 1:
            result = copy.deepcopy(arch[0])
        else:
            result = etree.Element("data")
            result.extend(copy.deepcopy(list(arch)))
        seen = {root}

        def extend(xid):
            for child in sorted(self.children.get(xid, ()), key=lambda x: (
                self.priorities.get(x, 16), len(self.closure(x.split(".")[0])),
                self.order.get(x, 0))):
                if child in seen or child == exclude or not self.view_modules[child] & modules:
                    continue
                seen.add(child)
                for spec in _specs(self.arches.get(child, ())):
                    if _apply_spec(result, spec) is not True and child.split(".")[0] != exclude.split(".")[0]:
                        self.incomplete_combinations.add((parent, frozenset(modules), exclude))
                extend(child)
        extend(root)
        return result


def _locate(arch, spec):
    if spec.tag == "xpath":
        return arch.xpath(spec.get("expr", ""), extensions={
            (None, "hasclass"): lambda ctx, *names: all(
                name in ctx.context_node.get("class", "").split() for name in names)
        })
    for node in arch.iter(spec.tag):
        if spec.tag == "field":
            if node.get("name") == spec.get("name"):
                return [node]
        elif all(node.get(k) == v for k, v in spec.attrib.items() if k not in ("position", "version")):
            return [node]
    return []


def _apply_spec(arch, spec):
    try:
        matches = _locate(arch, spec)
    except etree.XPathError:
        return None  # custom XPath extension: cannot evaluate statically
    if not matches:
        return False
    node = matches[0]
    if not isinstance(node, etree._Element):
        return None
    position = spec.get("position", "inside")
    if position == "attributes":
        for attr in spec:
            if attr.tag != "attribute" or not attr.get("name"):
                continue
            name = attr.get("name")
            if attr.get("add") is not None or attr.get("remove") is not None:
                sep = attr.get("separator", ",")
                values = node.get(name, "").split(sep)
                values = [v for v in values if v and v not in attr.get("remove", "").split(sep)]
                values.extend(v for v in attr.get("add", "").split(sep) if v)
                node.set(name, sep.join(values))
            elif attr.text is None:
                node.attrib.pop(name, None)
            else:
                node.set(name, attr.text)
        return True
    children = []
    for child in spec:
        if not isinstance(child.tag, str):
            continue
        if child.get("position") == "move":
            try:
                moved = _locate(arch, child)
            except etree.XPathError:
                return None
            if not moved or moved[0].getparent() is None:
                return None
            moved[0].getparent().remove(moved[0])
            children.append(moved[0])
        else:
            if "$0" in "".join(child.itertext()):
                return None
            children.append(copy.deepcopy(child))
    if position == "inside":
        node.extend(children)
    elif position in ("before", "after", "replace") and node.getparent() is not None:
        parent = node.getparent()
        offset = parent.index(node) + (position == "after")
        for child in children:
            parent.insert(offset, child)
            offset += 1
        if position == "replace":
            parent.remove(node)
    elif position == "replace" and node is arch and len(children) == 1:
        replacement = children[0]
        arch.clear()
        arch.tag, arch.text = replacement.tag, replacement.text
        arch.attrib.update(replacement.attrib)
        arch.extend(list(replacement))
    else:
        return None
    return True


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


def check_module(module, index, reference_modules, menu_parent_hints=()):
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
        if index.precisions:
            for node in root.iter():
                if not isinstance(node.tag, str):
                    continue
                digits = node.get("digits")
                if digits and re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]*", digits) and digits not in index.precisions:
                    yield path, node.sourceline, f"Unknown target decimal precision {digits!r} in XML digits"
        for xid, parent, arch, report_node in _views(root, module.name):
            if parent is None or arch is None:
                continue
            if parent not in index.views:
                if parent.split(".")[0] in reference_modules:
                    yield path, report_node.sourceline, (
                        f"parent view {parent} does not exist in the target Odoo"
                    )
                continue
            owner = parent.split(".")[0]
            if complete and owner in index.modules and owner not in closure:
                # its anchors cannot be found: the real error is the dependency
                # (installed only if another module happens to install it first)
                yield path, report_node.sourceline, _missing_depends(
                    f"parent view {parent}", owner
                )
                continue
            # the view itself does not count: it holds the anchors
            available = index.available(index.root(parent), closure if complete else index.modules, exclude={xid})
            combined = index.combined(parent, closure if complete else index.modules, xid)
            partial_arch = (parent, frozenset(closure if complete else index.modules), xid) in index.incomplete_combinations
            reported = set()
            for node, key, added in _anchors(arch):
                if combined is not None:
                    continue  # exact evaluation also accounts for attribute edits
                if key not in available and key not in added:
                    if id(node) in reported:
                        continue
                    reported.add(id(node))
                    yield path, node.sourceline, (
                        f"{_describe(key)} not found in the view {parent} of the target"
                        f" Odoo (nor in any view of its inheritance tree): the view will"
                        f" not install"
                    )
            if combined is not None:
                for node in _specs(arch):
                    valid = _apply_spec(combined, node)
                    if valid is None:
                        yield path, node.sourceline, f"[incomplete] Selector or inheritance operation in {parent} requires runtime validation"
                    if valid is False and id(node) not in reported:
                        selector = node.get("expr") if node.tag == "xpath" else etree.tostring(node, encoding="unicode").split(">")[0] + ">"
                        keys = [key for spec, key, _ in _anchors(arch) if spec is node]
                        if keys and any(key not in _keys(combined) for key in keys):
                            selector = _describe(next(key for key in keys if key not in _keys(combined)))
                        else:
                            selector = "Exact selector " + selector
                        yield path, node.sourceline, (
                            ("[incomplete] " if partial_arch else "") + f"{selector} not found in the combined view {parent}"
                            + (" (incomplete dependencies; verify with the missing modules)" if not complete else "")
                        )
        yield from _check_xmlids(
            path, root, module.name, index, reference_modules,
            closure if complete else None, menu_parent_hints,
        )


def _missing_depends(what, owner):
    return (
        f"{what} comes from the module '{owner}', which is not in the dependencies of the"
        f" module: add it to 'depends'"
    )


def _menu_parent_message(ref, hints, index):
    """Explain where surviving children of a removed standard menu moved."""
    moves = []
    for old_parent, child, new_parent, evidence in hints:
        if old_parent == ref and child in index.xmlids and new_parent in index.xmlids:
            moves.append((new_parent, child, evidence))
    if not moves:
        return f"XML id {ref} does not exist in the target Odoo"
    details = "; ".join(
        f"{new_parent} (former child {child})" + (f" [{evidence}]" if evidence else "")
        for new_parent, child, evidence in sorted(set(moves))
    )
    return (
        f"menu parent {ref} does not exist in the target Odoo; possible target parents"
        f" inferred from its surviving former children: {details}. Review the intended"
        " functional section before replacing the parent"
    )


def _check_xmlids(path, root, module_name, index, reference_modules, closure=None,
                  menu_parent_hints=()):
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
                    if node.tag == "menuitem" and node.get("parent") == ref:
                        message = _menu_parent_message(ref, menu_parent_hints, index)
                    else:
                        message = f"XML id {ref} does not exist in the target Odoo"
                    yield path, node.sourceline, message
            elif closure is not None and module not in closure:
                # works only if another module happens to install it first
                yield path, node.sourceline, _missing_depends(f"XML id {ref}", module)
