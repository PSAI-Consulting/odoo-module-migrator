# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Check that the models used by a module exist in the target Odoo.

A class inheriting a model that does not exist anymore (``_inherit`` /
``_inherits``), or a relational field whose comodel does not exist, prevents
the module from installing (e.g. ``barcodes.barcode_events_mixin`` or
``stock.valuation.layer`` in 20.0). The models available to a module are the
ones defined by the module and by its dependencies (``depends`` closure):
a model is reported only when it is defined nowhere there.
"""

import ast
import collections
import csv
import pathlib
import re

from .cache import cached_summary

RELATIONAL = {"Many2one", "One2many", "Many2many", "Many2oneReference"}


def _str_values(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _candidate_python_files(module):
    for path in pathlib.Path(module).rglob("*.py"):
        parts = path.relative_to(module).parts
        if path.name in {"__manifest__.py", "__openerp__.py", "__terp__.py"}:
            continue
        if parts and parts[0] in ("tests", "static", "migrations", "upgrades"):
            continue
        yield path


def loaded_python_files(module):
    """Python files reachable from the addon's root ``__init__.py``.

    Odoo imports the addon package, then ordinary relative imports decide
    which model, wizard and controller files execute. If the root initializer
    is absent, keep the historical all-files fallback so an incomplete source
    tree is still analysable without false dead-code claims.
    """
    module = pathlib.Path(module)
    candidates = set(_candidate_python_files(module))
    root = module / "__init__.py"
    if root not in candidates:
        return candidates
    loaded, pending = set(), [root]
    while pending:
        path = pending.pop()
        if path in loaded:
            continue
        loaded.add(path)
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, ValueError):
            # An initializer that cannot be parsed may load modules
            # dynamically. Avoid calling its children dead code.
            return candidates
        package = path.relative_to(module).parent.parts
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = tuple(alias.name.split("."))
                    for prefix in (("odoo", "addons", module.name), (module.name,)):
                        if parts[: len(prefix)] == prefix:
                            add_parts = parts[len(prefix) :]
                            file_path = module.joinpath(*add_parts).with_suffix(".py")
                            package_init = module.joinpath(*add_parts, "__init__.py")
                            for candidate in (file_path, package_init):
                                if candidate in candidates and candidate not in loaded:
                                    pending.append(candidate)
                continue
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level:
                keep = len(package) - (node.level - 1)
                if keep < 0:
                    continue
                base = package[:keep] + tuple((node.module or "").split("."))
                base = tuple(part for part in base if part)
            else:
                absolute = tuple((node.module or "").split("."))
                base = None
                for prefix in (("odoo", "addons", module.name), (module.name,)):
                    if absolute[: len(prefix)] == prefix:
                        base = absolute[len(prefix) :]
                        break
                if base is None:
                    continue

            def add(parts):
                file_path = module.joinpath(*parts).with_suffix(".py")
                package_init = module.joinpath(*parts, "__init__.py")
                for candidate in (file_path, package_init):
                    if candidate in candidates and candidate not in loaded:
                        pending.append(candidate)

            if node.module:
                add(base)
            for alias in node.names:
                if alias.name != "*":
                    add(base + tuple(alias.name.split(".")))
    return loaded


def unimported_python_files(module):
    """Relevant Python files/packages that Odoo will not import."""
    module = pathlib.Path(module)
    candidates = set(_candidate_python_files(module))
    if not (module / "__init__.py").is_file():
        return []
    missing = candidates - loaded_python_files(module)
    result = []
    for path in sorted(missing):
        parents = path.relative_to(module).parents
        if any(
            (parent_init := module / parent / "__init__.py") != path
            and parent_init in missing
            for parent in parents
        ):
            continue
        result.append(path)
    return result


def _python_files(module):
    yield from sorted(loaded_python_files(module))


NAME_RE = re.compile(r"""^\s{4}_name\s*=\s*['"]([\w.]+)['"]""", re.M)


def _classes(path):
    """(lineno, _name, _inherit list, _inherits keys, [(line, comodel)])."""
    try:
        tree = ast.parse(path.read_bytes())
    except (SyntaxError, ValueError):
        # newer Python syntax (Odoo 20 needs 3.12): the model names are enough
        text = path.read_bytes().decode("utf-8", "replace")
        for match in NAME_RE.finditer(text):
            yield text.count("\n", 0, match.start()) + 1, match.group(1), [], [], []
        return
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        name, inherit, inherits, comodels = None, [], [], []
        for stmt in cls.body:
            target = None
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                target = stmt.targets[0].id
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                target = stmt.target.id
            if target is None or stmt.value is None:
                continue
            if target == "_name":
                name = (_str_values(stmt.value) or [None])[0]
            elif target == "_inherit":
                inherit = _str_values(stmt.value)
            elif target == "_inherits" and isinstance(stmt.value, ast.Dict):
                inherits = [k.value for k in stmt.value.keys if isinstance(k, ast.Constant)]
            elif (
                isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Attribute)
                and stmt.value.func.attr in RELATIONAL
                and isinstance(stmt.value.func.value, ast.Name) and stmt.value.func.value.id == "fields"
            ):
                comodel = None
                if stmt.value.args and isinstance(stmt.value.args[0], ast.Constant):
                    comodel = stmt.value.args[0].value
                for kw in stmt.value.keywords:
                    if kw.arg == "comodel_name" and isinstance(kw.value, ast.Constant):
                        comodel = kw.value.value
                if isinstance(comodel, str) and "." in comodel:
                    comodel_line = stmt.lineno
                    comodels.append((comodel_line, comodel))
        if name or inherit:
            yield cls.lineno, name, inherit, inherits, comodels


# ---------------------------------------------------------------------------
# Fields of the models: paths of @api.depends / related=
# ---------------------------------------------------------------------------

# fields every model has (odoo/orm/models.py: id, display_name, log access)
MAGIC_FIELDS = {"id", "display_name", "create_uid", "create_date", "write_uid", "write_date"}
BASE_ATTRIBUTES = {"env", "ids", "pool"}
# Public ORM methods inherited by every regular, abstract and transient model.
# The core ``odoo/orm/models.py`` is not an addon and is therefore absent from
# normal addons-path indexing (bundled mode has no core checkout either).
BASE_METHODS = {
    "browse", "check_access", "check_access_rights", "check_access_rule",
    "copy", "copy_data", "create", "default_get", "ensure_one", "exists",
    "fields_get", "filtered", "filtered_domain", "flush_model",
    "flush_recordset", "get_metadata", "invalidate_model",
    "get_external_id", "_get_external_ids",
    "invalidate_recordset", "mapped", "modified", "name_create", "read",
    "read_group", "search", "_search", "search_count", "search_fetch",
    "search_read",
    "sorted", "sudo", "unlink", "update", "with_company", "with_context",
    "with_env", "with_prefetch", "with_user", "write",
}
# fields added at run time: custom fields, reified groups of res.users (<= 18.0)
DYNAMIC_FIELD_RE = re.compile(r"^(x_|in_group_|sel_groups_)")
# regex fallback (newer Python syntax): over-approximation, every field of the
# file is given to every model of the file
FIELD_ASSIGN_RE = re.compile(r"^\s{4}(\w+)\s*(?::[^=\n]+)?=\s*[\w.]*\b[A-Z]\w*\(", re.M)
MODEL_DECL_RE = re.compile(r"^\s{4}_(?:name|inherit)\s*=\s*(\[[^\]]*\]|.*)$", re.M)
QUOTED_MODEL_RE = re.compile(r"""['"]([a-z0-9_]+(?:\.[a-z0-9_]+)+)['"]""")


def _call_name(node):
    if isinstance(node, ast.Call):
        func = node.func
        return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    return None


def _class_infos(tree):
    """Per model class: model, _name, parents, transient, fields {name:
    comodel or None}, paths [(line, 'depends' | 'related', 'a.b.c')]."""
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        name, inherit, inherits, fields, paths = None, [], [], {}, []
        for stmt in cls.body:
            target = None
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                target = stmt.targets[0].id
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                target = stmt.target.id
            if target is not None and stmt.value is not None:
                if target == "_name":
                    name = (_str_values(stmt.value) or [None])[0]
                elif target == "_inherit":
                    inherit = _str_values(stmt.value)
                elif target == "_inherits" and isinstance(stmt.value, ast.Dict):
                    inherits = [k.value for k in stmt.value.keys if isinstance(k, ast.Constant)]
                elif (_call_name(stmt.value) or "")[:1].isupper():
                    # a field (fields.Char(...), Many2one(...)...): any call of a
                    # capitalized name counts (over-approximation, no false positive)
                    call = stmt.value
                    comodel = None
                    if _call_name(call) in RELATIONAL - {"Many2oneReference"}:
                        values = (_str_values(call.args[0]) if call.args else []) or [
                            v for kw in call.keywords if kw.arg == "comodel_name"
                            for v in _str_values(kw.value)
                        ]
                        comodel = values[0] if values and "." in values[0] else None
                    fields[target] = comodel
                    for kw in call.keywords:
                        if kw.arg == "related" and isinstance(kw.value, ast.Constant) \
                                and isinstance(kw.value.value, str):
                            paths.append((kw.value.lineno, "related", kw.value.value))
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in stmt.decorator_list:
                    if isinstance(deco, ast.Call) and _call_name(deco) == "depends":
                        for arg in deco.args:
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                paths.append((arg.lineno, "depends", arg.value))
        model = name or (inherit[0] if inherit else None)
        if not model:
            continue
        bases = {
            base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
            for base in cls.bases
        }
        parents = {m for m in [*inherit, *inherits] if m != model}
        yield model, name, parents, bases, fields, paths


def method_signature(node):
    """Return a JSON-compatible signature without the recordset argument."""
    positional = [
        *(('positional_only', arg) for arg in node.args.posonlyargs),
        *(('positional_or_keyword', arg) for arg in node.args.args),
    ]
    defaults = [None] * (len(positional) - len(node.args.defaults)) + [
        ast.unparse(default) for default in node.args.defaults
    ]
    parameters = [
        {"kind": kind, "name": arg.arg, "default": default}
        for (kind, arg), default in zip(positional, defaults)
    ]
    if parameters and parameters[0]["name"] in {"self", "cls"}:
        parameters.pop(0)
    parameters.extend(
        {
            "kind": "keyword_only",
            "name": arg.arg,
            "default": ast.unparse(default) if default is not None else None,
        }
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults)
    )
    return {
        "parameters": parameters,
        "vararg": node.args.vararg.arg if node.args.vararg else None,
        "kwarg": node.args.kwarg.arg if node.args.kwarg else None,
    }


def signature_key(signature):
    return (
        tuple(
            (item["kind"], item["name"], item.get("default"))
            for item in signature["parameters"]
        ),
        signature.get("vararg"),
        signature.get("kwarg"),
    )


def format_signature(signature):
    values = []
    positional = [
        item for item in signature["parameters"] if item["kind"] != "keyword_only"
    ]
    keyword_only = [
        item for item in signature["parameters"] if item["kind"] == "keyword_only"
    ]
    positional_only = sum(item["kind"] == "positional_only" for item in positional)
    for position, item in enumerate(positional, 1):
        value = item["name"]
        if item.get("default") is not None:
            value += "=" + item["default"]
        values.append(value)
        if positional_only and position == positional_only:
            values.append("/")
    if signature.get("vararg"):
        values.append("*" + signature["vararg"])
    elif keyword_only:
        values.append("*")
    for item in keyword_only:
        value = item["name"]
        if item.get("default") is not None:
            value += "=" + item["default"]
        values.append(value)
    if signature.get("kwarg"):
        values.append("**" + signature["kwarg"])
    return "(" + ", ".join(values) + ")"


def source_summary(path):
    """JSON-compatible model metadata; one parse per source revision."""
    text = path.read_bytes()
    if b"_name" not in text and b"_inherit" not in text:
        return []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        text = text.decode("utf-8", "replace")
        models = {m for decl in MODEL_DECL_RE.findall(text) for m in QUOTED_MODEL_RE.findall(decl)}
        return [dict(model=m, name=m if m in NAME_RE.findall(text) else None,
                     parents=list(models - {m}), bases=[],
                     fields=dict.fromkeys(FIELD_ASSIGN_RE.findall(text)),
                     methods=re.findall(r"^    (?:async )?def (\w+)\(", text, re.M),
                     method_depends={}, method_calls={}, types={}, company=[])
                for m in sorted(models)]
    result = []
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        infos = list(_class_infos(ast.Module(body=[cls], type_ignores=[])))
        if not infos:
            continue
        model, name, parents, bases, fields, _ = infos[0]
        kinds, company, method_depends, method_calls = {}, [], {}, {}
        for stmt in cls.body:
            target = stmt.target if isinstance(stmt, ast.AnnAssign) else (
                stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None)
            call = getattr(stmt, "value", None)
            if isinstance(target, ast.Name) and target.id in fields and isinstance(call, ast.Call):
                kinds[target.id] = _call_name(call)
                if any(k.arg == "company_dependent" and isinstance(k.value, ast.Constant)
                       and k.value.value is True for k in call.keywords):
                    company.append(target.id)
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                dependencies = []
                for decorator in stmt.decorator_list:
                    if not (
                        isinstance(decorator, ast.Call)
                        and _call_name(decorator) == "depends"
                    ):
                        continue
                    dependencies.extend(
                        arg.value
                        for arg in decorator.args
                        if isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                    )
                if dependencies:
                    method_depends[stmt.name] = dependencies
                calls = {
                    node.func.attr
                    for node in ast.walk(stmt)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and (
                        node.func.attr.startswith(("_affects_", "_prepare_"))
                        or node.func.attr.startswith("_get_")
                        and node.func.attr.endswith("_domain")
                    )
                }
                if calls:
                    method_calls[stmt.name] = sorted(calls)
        result.append(dict(model=model, name=name, parents=sorted(parents), bases=sorted(bases),
                           fields=fields, methods=[s.name for s in cls.body
                           if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))],
                           method_signatures={s.name: method_signature(s) for s in cls.body
                           if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))},
                           method_depends=method_depends, method_calls=method_calls,
                           types=kinds, company=company))
    return result


class ModelIndex:
    def __init__(self):
        self.models = collections.defaultdict(set)  # module -> models it defines
        self.depends = {}
        # all the indexed modules together (a field found anywhere is not reported)
        self.fields = collections.defaultdict(set)      # model -> field names
        self.comodels = collections.defaultdict(set)    # (model, field) -> comodels
        self.parents = collections.defaultdict(set)     # model -> _inherit / _inherits
        self.defined = set()                            # models with a _name
        self.transient = set()
        self.abstract = set()
        self.field_owners = collections.defaultdict(set)
        self.methods = collections.defaultdict(set)
        self.method_owners = collections.defaultdict(set)
        self.method_signatures = collections.defaultdict(list)
        self.method_depends = collections.defaultdict(set)
        self.method_calls = collections.defaultdict(set)
        self.field_types = collections.defaultdict(set)
        self.company_fields = set()
        self.renamed_methods = {}
        self.enterprise_modules = set()

    def _add_fields(self, path, owner=""):
        text = path.read_bytes()
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            text = text.decode("utf-8", "replace")
            models = {m for decl in MODEL_DECL_RE.findall(text) for m in QUOTED_MODEL_RE.findall(decl)}
            names = set(FIELD_ASSIGN_RE.findall(text))
            for model in models:
                self.fields[model] |= names | MAGIC_FIELDS
                self.parents[model] |= models - {model}
                self.methods[model].update(BASE_METHODS)
                for method in BASE_METHODS:
                    self.method_owners[model, method].add("base")
            # models defined by _name only can't be told apart: all are defined
            self.defined |= set(NAME_RE.findall(text))
            return
        for model, name, parents, bases, fields, _paths in _class_infos(tree):
            if name:
                self.defined.add(name)
            if "TransientModel" in bases:
                self.transient.add(model)
            if "AbstractModel" in bases:
                self.abstract.add(model)
            self.parents[model] |= parents
            self.fields[model] |= set(fields) | MAGIC_FIELDS
            self.methods[model].update(BASE_METHODS)
            for method in BASE_METHODS:
                self.method_owners[model, method].add("base")
            for field, comodel in fields.items():
                if comodel:
                    self.comodels[(model, field)].add(comodel)

    def _add_summary(self, path, owner):
        summary = cached_summary(path, source_summary)
        for info in summary:
            model = info["model"]
            if info["name"]:
                self.models[owner].add(info["name"])
                self.defined.add(info["name"])
            self.parents[model].update(info["parents"])
            self.fields[model].update(MAGIC_FIELDS)
            if "TransientModel" in info["bases"]:
                self.transient.add(model)
            if "AbstractModel" in info["bases"]:
                self.abstract.add(model)
            self.fields[model].update(info["fields"])
            for field, comodel in info["fields"].items():
                self.field_owners[model, field].add(owner)
                if comodel:
                    self.comodels[model, field].add(comodel)
            for method in info["methods"]:
                self.methods[model].add(method)
                self.method_owners[model, method].add(owner)
                signature = info.get("method_signatures", {}).get(method)
                if (
                    signature
                    and signature_key(signature)
                    not in {
                        signature_key(existing)
                        for existing in self.method_signatures[model, method, owner]
                    }
                ):
                    self.method_signatures[model, method, owner].append(signature)
            for method, dependencies in info.get("method_depends", {}).items():
                self.method_depends[model, method, owner].update(dependencies)
            for method, calls in info.get("method_calls", {}).items():
                self.method_calls[model, method, owner].update(calls)
            self.methods[model].update(BASE_METHODS)
            for method in BASE_METHODS:
                self.method_owners[model, method].add("base")
            for field, kind in info["types"].items():
                self.field_types[model, field].add(kind)
            self.company_fields.update((model, f) for f in info["company"])

    def ancestors(self, model):
        result, todo = set(), [model]
        while todo:
            current = todo.pop()
            if current not in result:
                result.add(current)
                todo.extend(self.parents.get(current, ()))
        return result

    def wrong_field(self, model, dotted, kind):
        """(field, model) of the first field of the path that does not exist,
        when every model on the way is known for sure; else None."""
        if model in self.abstract:
            return None  # a mixin may rely on the fields of the models using it
        model0_transient = model in self.transient
        current = model
        names = dotted.split(".")
        for position, field in enumerate(names):
            if not re.fullmatch(r"\w+", field):
                return None
            # odoo/orm/fields.py resolve_depends: the dependencies of a transient
            # model on regular models are not checked
            if kind == "depends" and model0_transient and current not in self.transient:
                return None
            ancestors = self.ancestors(current)
            if not ancestors <= self.defined:
                return None  # a parent model unknown: its fields are unknown
            if field in MAGIC_FIELDS or DYNAMIC_FIELD_RE.match(field):
                return None
            if not any(field in self.fields.get(m, ()) for m in ancestors):
                return field, current
            # the definition on the model itself wins over its parents
            comodels = set(self.comodels.get((current, field), ())) or set().union(
                *(self.comodels.get((m, field), set()) for m in ancestors)
            )
            if position + 1 < len(names):
                if len(comodels) != 1:
                    return None  # not relational, or comodel unknown
                current = comodels.pop()
        return None

    def add_module(self, module):
        module = pathlib.Path(module)
        try:
            manifest = ast.literal_eval(
                (module / "__manifest__.py").read_text(encoding="utf-8", errors="replace").lstrip()
            )
        except (ValueError, SyntaxError):
            manifest = {}
        self.depends[module.name] = manifest.get("depends", [])
        if manifest.get("license") == "OEEL-1":
            self.enterprise_modules.add(module.name)
        for path in _python_files(module):
            self._add_summary(path, module.name)

    @classmethod
    def build(cls, paths):
        index = cls()
        from .views import _module_dirs
        for module in _module_dirs(paths):
            index.add_module(module)
        return index

    def unknown_dependencies(self, module):
        """Dependencies (direct or not) absent from the indexed addons paths."""
        result, todo, seen = [], [module, "base"], set()
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            if name not in self.depends:
                result.append(name)
            todo.extend(self.depends.get(name, ()))
        return sorted(result)

    def closure(self, module):
        result, todo = set(), [module, "base"]
        while todo:
            name = todo.pop()
            if name not in result:
                result.add(name)
                todo.extend(self.depends.get(name, ()))
        return result

    def available(self, module):
        result = set()
        for name in self.closure(module):
            result |= self.models.get(name, set())
        return result

    def owners(self, model):
        """The indexed modules defining `model` (_name)."""
        return sorted(name for name, models in self.models.items() if model in models)


def check_module(module, index):
    """Yield (path, line, message) for the models that do not exist."""
    module = pathlib.Path(module)
    closure = index.closure(module.name)
    available = index.available(module.name)
    if not index.models.get("base"):
        return  # no reference addons indexed: nothing can be checked
    # all the dependencies indexed: a model defined by another module is known
    # for sure to be outside the dependencies
    complete = all(name in index.depends for name in closure)

    def missing(model, what):
        owners = index.owners(model)
        if not complete and not owners:
            return (f"[incomplete] Model '{model}' ({what}) not found in available sources;"
                    " supply missing dependencies to verify it")
        if owners:
            if not complete:
                return (f"[incomplete] Model '{model}' ({what}) is provided by {', '.join(owners)};"
                        " verify the dependency chain when missing addons are supplied")
            return (
                f"[model] '{model}' ({what}) is defined by the module(s) {', '.join(owners)},"
                f" not in the dependencies of the module: add one of them to 'depends'"
            )
        return None
    for path in _python_files(module):
        for line, name, inherit, inherits, comodels in _classes(path):
            for parent in [*inherit, *inherits]:
                if parent != name and parent not in available:
                    yield path, line, missing(parent, "inherited") or (
                        f"[model] '{parent}' (inherited) does not exist in the target Odoo,"
                        f" nor in the dependencies of the module: the module will not install"
                    )
            for comodel_line, comodel in comodels:
                if comodel not in available:
                    yield path, comodel_line, missing(comodel, "comodel of a relational field") or (
                        f"[model] '{comodel}' (comodel of a relational field) does not exist"
                        f" in the target Odoo, nor in the dependencies of the module"
                    )


def check_abstract_access(module, index):
    """Yield access rows that target an AbstractModel and therefore do nothing."""
    module = pathlib.Path(module)
    for filename in ("ir.access.csv", "ir.model.access.csv"):
        path = module / "security" / filename
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = csv.DictReader(stream)
                for line, row in enumerate(rows, 2):
                    raw = next(
                        (
                            row.get(column, "").strip()
                            for column in ("model_id", "model_id/id", "model_id:id")
                            if row.get(column, "").strip()
                        ),
                        "",
                    )
                    local = raw.rsplit(".", 1)[-1]
                    model = raw if raw in index.abstract else next(
                        (
                            candidate
                            for candidate in index.abstract
                            if local == "model_" + candidate.replace(".", "_")
                        ),
                        None,
                    )
                    if model:
                        yield path, line, (
                            f"[access] Access rights target abstract model '{model}'; "
                            "AbstractModel has no records of its own, so this row "
                            "has no effect"
                        )
        except (OSError, csv.Error, UnicodeError):
            continue


def check_tracking_without_mail(module, index):
    """Yield fields declaring tracking= on a model that does not inherit
    mail.thread: Odoo 20 ignores the parameter and logs 'unknown parameter'."""
    for path in _python_files(pathlib.Path(module)):
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, ValueError):
            continue
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            infos = list(_class_infos(ast.Module(body=[cls], type_ignores=[])))
            if not infos:
                continue
            model, _name, parents, _bases, _fields, _paths = infos[0]
            lineage = index.ancestors(model) | parents
            for parent in parents:
                lineage |= index.ancestors(parent)
            # Only conclude when every model of the lineage is known.
            if "mail.thread" in lineage or any(m not in index.defined for m in lineage):
                continue
            for stmt in cls.body:
                if not (
                    isinstance(stmt, ast.Assign)
                    and isinstance(stmt.value, ast.Call)
                    and isinstance(stmt.targets[0], ast.Name)
                ):
                    continue
                field = stmt.targets[0].id
                for kw in stmt.value.keywords:
                    if kw.arg == "tracking" and not (
                        isinstance(kw.value, ast.Constant) and not kw.value.value
                    ):
                        yield path, kw.value.lineno, (
                            f"[model] Field '{model}.{field}' "
                            "uses tracking= but the model does not inherit mail.thread; "
                            "Odoo ignores it and logs 'unknown parameter'. Remove it or "
                            "inherit mail.thread"
                        )


def check_field_paths(module, index):
    """Yield (path, line, message) for the paths of @api.depends / related=
    of the module going through a field that does not exist: Odoo does not
    load the registry (odoo/orm/fields.py: "Wrong @depends on ...", "Field ...
    referenced in related field definition ... does not exist")."""
    module = pathlib.Path(module)
    if not index.models.get("base"):
        return
    incomplete = bool(index.unknown_dependencies(module.name))
    # a field may come from a dependency that is not indexed
    for path in _python_files(module):
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, ValueError):
            continue
        for model, _name, _parents, _bases, _fields, paths in _class_infos(tree):
            for line, kind, dotted in paths:
                wrong = index.wrong_field(model, dotted, kind)
                if not wrong:
                    continue
                field, field_model = wrong
                what = "@api.depends" if kind == "depends" else "related="
                yield path, line, (
                    f"[model] {what} '{dotted}' of {model}: the field '{field}' does not exist"
                    f" on {field_model} in the target Odoo (nor in any indexed module): the"
                    + (" verification is incomplete: supply missing dependencies" if incomplete else " registry will not load")
                )
