#!/usr/bin/env python3
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Names that cannot be imported from ``odoo.tools`` anymore, per version jump.

``odoo/tools/__init__.py`` re-exports its submodules (``from .mail import *``,
``from .misc import *``, ``from .query import Query``...). When a submodule
gets an ``__all__`` or when ``__init__`` stops re-exporting a name,
``from odoo.tools import X`` breaks while ``from odoo.tools.<mod> import X``
still works. This script compares two branches of a bare Odoo repository
(``git cat-file``, no checkout) by *resolving* the bindings with ``ast``:

* the namespace of ``odoo.tools`` = every top-level binding of
  ``odoo/tools/__init__.py`` (star imports expanded with ``__all__``, or the
  public names when there is none) + its submodules (``from odoo.tools import
  misc`` always works) + the names served by a module ``__getattr__``
  (deprecated: they still work);
* every binding is followed through the ``odoo`` imports down to its origin:
  a definition (``def`` / ``class`` / assignment) in an ``odoo`` module, an
  ``odoo`` module, or an import from another library (``from markupsafe
  import Markup``);
* a name exported in N and not in N+1 is then looked up in N+1: still defined
  in its module (``moved``: only the re-export was lost), else defined at top
  level in exactly one other module of ``odoo/`` with the very same code
  (``ast.dump`` equal: ``moved``), else ``removed`` (with a ``hint`` when a
  different definition exists elsewhere: to check by hand, never rewritten).
  A target under ``odoo.orm`` is replaced by the public module re-exporting
  it (``odoo.api``, ``odoo.models``, ``odoo.fields``) when there is one.

Same comparison for ``from odoo.tools.<mod> import X`` (definitions of the
submodules of ``odoo.tools`` that their module does not bind anymore: public
names, and private functions / classes).

Ignored, because not provable or not imported by anyone: names bound only
under ``if``/``try`` (``if TYPE_CHECKING`` / ``if __name__ == '__main__'``
bodies are not bindings at all), plain module imports (``os``, ``re``...),
``TypeVar`` assignments, private modules (``_monkeypatches``...).

Every rule carries its proof: the commit of N..N+1 that changed it (``git log
-S`` / ``-G`` on the file concerned) and the files of both branches.

    py -3.12 tools/extract_tools_exports.py --repo D:/Odoo/.repos/odoo.git \\
        --from 19.0 --to 20.0 \\
        --output odoo_module_migrate/migration_scripts/python_scripts/migrate_190_200/odoo_tools_imports.yaml

The Python running it must parse the sources of N+1 (20.0 uses PEP 695:
Python 3.12+); a file that cannot be parsed stops the script.
"""

import argparse
import ast
import functools
import os
import subprocess
import sys

# public modules re-exporting ORM objects: preferred to odoo.orm.<private module>
FACADES = ("odoo.api", "odoo.models", "odoo.fields", "odoo.exceptions")
TYPEVARS = {"TypeVar", "ParamSpec", "TypeVarTuple", "NewType"}


def git(repo, *args, check=True):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))
    return result.stdout.decode("utf-8", "replace") if result.returncode == 0 else ""


def _not_runtime(test):
    """``if TYPE_CHECKING:`` / ``if __name__ == '__main__':`` bodies bind nothing at import."""
    text = ast.unparse(test)
    return text in ("TYPE_CHECKING", "typing.TYPE_CHECKING") or text.replace('"', "'") == "__name__ == '__main__'"


def _target_names(target):
    """Names bound by an assignment target (not ``Image._initialized = 2``)."""
    if isinstance(target, ast.Name):
        yield target
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _target_names(elt)
    elif isinstance(target, ast.Starred):
        yield from _target_names(target.value)


class Branch:
    """The ``odoo`` package (without addons) of one branch, read with ``git cat-file``."""

    def __init__(self, repo, ref):
        self.repo, self.ref = repo, ref
        files = git(repo, "ls-tree", "-r", "--name-only", ref, "--", "odoo").splitlines()
        self.files = {f for f in files if f.endswith(".py") and not f.startswith("odoo/addons/")}
        paths = sorted(self.files)
        out = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "--batch"],
            input="".join(f"{ref}:{p}\n" for p in paths).encode(),
            capture_output=True, check=True,
        ).stdout
        self.sources, pos = {}, 0
        for path in paths:
            end = out.index(b"\n", pos)
            size = int(out[pos:end].split()[2])
            self.sources[path] = out[end + 1:end + 1 + size].decode("utf-8", "replace")
            pos = end + 1 + size + 1

    def path(self, dotted):
        base = dotted.replace(".", "/")
        for path in (f"{base}.py", f"{base}/__init__.py"):
            if path in self.files:
                return path
        return None

    def is_package(self, dotted):
        return (self.path(dotted) or "").endswith("/__init__.py")

    def submodules(self, dotted):
        prefix = dotted.replace(".", "/") + "/"
        result = set()
        for f in self.files:
            if f.startswith(prefix):
                rest = f[len(prefix):].split("/")
                name = rest[0][:-3] if len(rest) == 1 else rest[0]
                if (len(rest) == 1 or rest[1:] == ["__init__.py"]) and name != "__init__":
                    result.add(name)
        return result

    @functools.lru_cache(maxsize=None)
    def tree(self, dotted):
        path = self.path(dotted)
        if not path:
            return None
        try:
            return ast.parse(self.sources[path])
        except SyntaxError as e:
            # never read a module as empty: every name would look removed
            raise SystemExit(
                f"{self.ref}:{path} cannot be parsed by Python {sys.version.split()[0]} ({e}):"
                " run this script with the Python version of this Odoo branch (20.0: 3.12+)"
            ) from e

    def _absolute(self, dotted, node):
        if not node.level:
            return node.module
        parts = dotted.split(".")
        if not self.is_package(dotted):
            parts = parts[:-1]
        parts = parts[: len(parts) - (node.level - 1)]
        return ".".join(parts + ([node.module] if node.module else []))

    @functools.lru_cache(maxsize=None)
    def bindings(self, dotted):
        """({name: binding}, __all__ or None, names served by __getattr__).

        binding: ("def", module, node, conditional) | ("typevar", module, node, conditional)
        | ("from", module, name, conditional) | ("module", dotted, conditional)
        | ("ext", "from x import Y", conditional) | ("extmodule", "import x", conditional)
        """
        tree = self.tree(dotted)
        result, all_, getattr_names = {}, None, set()
        if tree is None:
            return result, all_, getattr_names

        def strings(node):
            return [e.value for e in getattr(node, "elts", []) if isinstance(e, ast.Constant)
                    and isinstance(e.value, str)]

        def walk(body, conditional):
            nonlocal all_
            for node in body:
                if isinstance(node, ast.If):
                    if not _not_runtime(node.test):
                        walk(node.body, True)
                    walk(node.orelse, True)
                elif isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
                    walk(node.body, True)
                    for handler in node.handlers:
                        walk(handler.body, True)
                    walk(node.orelse, True)
                    walk(node.finalbody, True)
                elif isinstance(node, ast.With):
                    walk(node.body, conditional)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    result[node.name] = ("def", dotted, node, conditional)
                    if node.name == "__getattr__":
                        for sub in ast.walk(node):
                            if isinstance(sub, ast.Compare) and isinstance(sub.left, ast.Name) \
                                    and sub.left.id == "name":
                                for comp in sub.comparators:
                                    getattr_names.update(strings(comp))
                                    if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                                        getattr_names.add(comp.value)
                elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    value = node.value
                    kind = "def"
                    if isinstance(value, ast.Call) and getattr(value.func, "id", getattr(value.func, "attr", "")) in TYPEVARS:
                        kind = "typevar"
                    for target in targets:
                        for name in _target_names(target):
                            if isinstance(name, ast.Name):
                                if name.id == "__all__":
                                    values = strings(value)
                                    all_ = (all_ or []) + values if isinstance(node, ast.AugAssign) \
                                        else values
                                elif not isinstance(node, ast.AugAssign) or name.id not in result:
                                    result[name.id] = (kind, dotted, node, conditional)
                elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                        and isinstance(node.value.func, ast.Attribute) \
                        and isinstance(node.value.func.value, ast.Name) \
                        and node.value.func.value.id == "__all__" and node.value.args:
                    all_ = (all_ or []) + strings(node.value.args[0])
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if alias.asname:
                            if top == "odoo":
                                result[alias.asname] = ("module", alias.name, conditional)
                            else:
                                result[alias.asname] = ("extmodule", f"import {alias.name}", conditional)
                        elif top == "odoo":
                            result[top] = ("module", "odoo", conditional)
                        else:
                            result[top] = ("extmodule", f"import {top}", conditional)
                elif isinstance(node, ast.ImportFrom):
                    module = self._absolute(dotted, node)
                    is_odoo = module == "odoo" or module.startswith("odoo.")
                    for alias in node.names:
                        if alias.name == "*":
                            if is_odoo:
                                for name in self.public(module):
                                    result[name] = ("from", module, name, conditional)
                            continue
                        if is_odoo:
                            result[alias.asname or alias.name] = ("from", module, alias.name, conditional)
                        else:
                            text = f"from {module} import {alias.name}"
                            if alias.asname:
                                text += f" as {alias.asname}"
                            result[alias.asname or alias.name] = ("ext", text, conditional)

        walk(tree.body, False)
        return result, all_, getattr_names

    def public(self, dotted):
        names, all_, _getattr = self.bindings(dotted)
        if all_ is not None:
            return list(all_)
        return [n for n in names if not n.startswith("_")]

    def resolve(self, dotted, name, _depth=0):
        """Origin of ``name`` imported from module ``dotted``: ("def"|"typevar", module,
        node, conditional) | ("module", dotted, conditional) | ("ext"|"extmodule", text,
        conditional) | ("getattr", module, None, False) | None."""
        if _depth > 20:
            return None
        names, _all, getattr_names = self.bindings(dotted)
        binding = names.get(name)
        if binding is None:
            if self.path(f"{dotted}.{name}"):
                return ("module", f"{dotted}.{name}", False)
            if name in getattr_names:
                return ("getattr", dotted, None, False)
            return None
        if binding[0] == "from":
            _kind, module, src, conditional = binding
            if self.path(f"{module}.{src}") and src not in self.bindings(module)[0]:
                return ("module", f"{module}.{src}", conditional)
            origin = self.resolve(module, src, _depth + 1)
            if origin and conditional:
                origin = origin[:-1] + (True,)
            return origin
        return binding

    def namespace(self, dotted):
        """{name: origin} of every name importable with ``from <dotted> import X``."""
        names, _all, getattr_names = self.bindings(dotted)
        result = {n: self.resolve(dotted, n) for n in names if not n.startswith("__")}
        for sub in self.submodules(dotted):
            result[sub] = ("module", f"{dotted}.{sub}", False)
        for name in getattr_names:
            result.setdefault(name, ("getattr", dotted, None, False))
        return result

    @functools.lru_cache(maxsize=None)
    def find_definitions(self, name):
        """{module: node} of the modules of ``odoo`` (not addons, not tests) defining
        ``name`` at top level, unconditionally."""
        result = {}
        for path in sorted(self.files):
            if "/tests/" in path or name not in self.sources[path]:
                continue
            dotted = path[:-3].replace("/", ".").removesuffix(".__init__")
            binding = self.bindings(dotted)[0].get(name)
            if binding and binding[0] == "def" and not binding[3]:
                result[dotted] = binding[2]
        return result

    def facade(self, module, name):
        """Public module re-exporting the definition of ``module.name``, else ``module``."""
        if module.startswith("odoo.orm."):
            for facade in FACADES:
                origin = self.resolve(facade, name) if self.path(facade) else None
                if origin and origin[0] == "def" and origin[1] == module and not origin[3]:
                    return facade
        return module


def _same(node_a, node_b):
    return ast.dump(node_a) == ast.dump(node_b)


class Proofs:
    def __init__(self, repo, ref_from, ref_to, enabled=True):
        self.repo, self.range, self.enabled = repo, f"{ref_from}..{ref_to}", enabled
        self.ref_from, self.ref_to = ref_from, ref_to

    @functools.lru_cache(maxsize=None)
    def commit(self, option, value, path, oldest=False):
        """Newest (or oldest) commit of the range changing ``value`` in ``path``
        (``value`` None: any change selected by ``option``)."""
        if not self.enabled or not path:
            return None
        args = ["log", "--format=%h %s", option, *([value] if value else []), self.range, "--", path]
        if oldest:
            args.insert(1, "--reverse")
        lines = git(self.repo, *args, check=False).splitlines()
        if not lines:
            return None
        sha, subject = lines[0].split(" ", 1)
        return f"odoo {sha} '{subject}'"

    def definition(self, name, path):
        """(pickaxe, commit) of the commit removing the definition of ``name`` from ``path``."""
        for value in (f"def {name}(", f"class {name}", f"{name} = ", f"{name}: ", name):
            found = self.commit("-S", value, path)
            if found:
                return value, found
        # the history of the file alone can hide the change (merges): whole directory
        for value in (f"def {name}(", f"class {name}", f"{name} = "):
            found = self.commit("-S", value, path.rsplit("/", 1)[0])
            if found:
                return None, found
        return None, None

    def deletion(self, path):
        """Commit deleting (or renaming) ``path``."""
        if not self.enabled or not path:
            return None
        lines = git(self.repo, "log", "--format=%h %s", "--no-renames", "--diff-filter=D",
                    self.range, "--", path, check=False).splitlines()
        if not lines:
            return None
        sha, subject = lines[0].split(" ", 1)
        return f"odoo {sha} '{subject}'"


def _export_proof(old, new, proofs, name, origin):
    """Why ``name`` is not exported by ``odoo.tools`` anymore."""
    init = "odoo/tools/__init__.py"
    first_hop = old.bindings("odoo.tools")[0].get(name)
    via = first_hop[1] if first_hop and first_hop[0] in ("from", "module") else None
    if via and via.startswith("odoo.tools."):
        sub = via.rsplit(".", 1)[1]
        old_star = f"from .{sub} import *" in old.sources[init]
        new_star = f"from .{sub} import *" in new.sources[init]
        if old_star and not new_star:
            return proofs.commit("-S", f"from .{sub} import *", init)
        if old_star and new.path(via):
            old_all, new_all = old.bindings(via)[1], new.bindings(via)[1]
            if old_all is None and new_all is not None:
                return proofs.commit("-G", r"^__all__ = ", new.path(via), oldest=True)
            if old_all and name in old_all and new_all is not None and name not in new_all:
                return proofs.commit("-G", f"[\"']{name}[\"']", new.path(via))
    found = proofs.commit("-S", name, init)
    if found:
        return found
    if origin and origin[0] in ("def", "typevar"):
        return proofs.definition(name, old.path(origin[1]))[1]
    return None


def _locate(old, new, proofs, name, origin):
    """(target module or None, hint or None) of an origin of the old branch in the new one.

    Moved: still defined by its module, or defined in exactly one other module with
    the same code, or by a commit that removed it from its old module and added it
    to the new one (a move whose code was adapted: proved by that commit)."""
    module = origin[1]
    if new.path(module):
        now = new.resolve(module, name)
        if now and now[0] == "def" and not now[3]:
            return new.facade(now[1], name), None
    found = new.find_definitions(name)
    same = [m for m, node in found.items() if _same(node, origin[2])]
    if len(same) != 1 and found:
        pickaxe, removal = proofs.definition(name, old.path(module))
        same = [m for m in found if pickaxe and removal and proofs.commit("-S", pickaxe, new.path(m)) == removal]
    if len(same) == 1:
        return new.facade(same[0], name), None
    return None, ", ".join(sorted(found)) or None


def compare(repo, ref_from, ref_to, with_proof=True):
    """Rules: [{from, name, to, proof, ...}] (``to`` None: not importable anymore)."""
    old, new = Branch(repo, ref_from), Branch(repo, ref_to)
    proofs = Proofs(repo, ref_from, ref_to, with_proof)
    rules = []
    old_ns, new_ns = old.namespace("odoo.tools"), new.namespace("odoo.tools")
    for name in sorted(set(old_ns) - set(new_ns)):
        origin = old_ns[name]
        if origin is None or origin[-1]:
            continue  # unresolved, or bound conditionally: not provable
        kind = origin[0]
        rule = {"from": "odoo.tools", "name": name}
        if kind == "ext":
            if origin[1].split()[1].split(".")[0] in ("odoo", "__future__"):
                continue
            rule["import"] = origin[1]
            rule["source"] = f"{ref_from} {old.path(old.bindings('odoo.tools')[0][name][1]) or ''}".strip()
        elif kind == "module":
            if name.startswith("_") or new.path(origin[1]) or not origin[1].startswith("odoo.tools."):
                continue
            rule["to"] = None
            rule["module"] = True
            rule["proof"] = proofs.deletion(old.path(origin[1]))
            rules.append(rule)
            continue
        elif kind == "def":
            rule["to"], hint = _locate(old, new, proofs, name, origin)
            if hint:
                rule["hint"] = hint
            rule["old"] = origin[1]
        else:
            continue
        if kind == "def" and rule["to"] not in (origin[1], new.facade(origin[1], name)):
            rule["proof"] = proofs.definition(name, old.path(origin[1]))[1]
        else:
            rule["proof"] = _export_proof(old, new, proofs, name, origin)
        rules.append(rule)
    # deprecated names served by a module __getattr__ in the new branch
    for name, origin in sorted(new_ns.items()):
        if origin and origin[0] == "getattr" and old_ns.get(name) and old_ns[name][0] == "def":
            target, _hint = _locate(old, new, proofs, name, old_ns[name])
            rules.append({
                "from": "odoo.tools", "name": name, "to": target, "deprecated": True,
                "proof": proofs.commit("-S", f"'{name}'", "odoo/tools/__init__.py", oldest=True),
            })
    # from odoo.tools.<mod> import X
    for sub in sorted(old.submodules("odoo.tools")):
        module = f"odoo.tools.{sub}"
        if sub.startswith("_"):
            continue
        new_names = new.namespace(module) if new.path(module) else {}
        for name, binding in sorted(old.bindings(module)[0].items()):
            if binding[0] != "def" or binding[3] or name in new_names or name.startswith("__"):
                continue
            # private names: only functions / classes (``from .query import _generate_table_alias``)
            if name.startswith("_") and not isinstance(binding[2], (ast.FunctionDef, ast.ClassDef)):
                continue
            target, hint = _locate(old, new, proofs, name, binding)
            rule = {"from": module, "name": name, "to": target}
            if hint:
                rule["hint"] = hint
            rule["proof"] = proofs.definition(name, old.path(module))[1]
            rules.append(rule)
    return rules


def _q(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    return "'" + str(value).replace("'", "''") + "'"


def dump(rules, ref_from, ref_to):
    lines = [
        f"# from odoo.tools[.<module>] import X: names not importable anymore in {ref_to}.",
        f"# Generated by tools/extract_tools_exports.py --from {ref_from} --to {ref_to} (do not edit:",
        "# re-run it). to: module to import it from instead (same definition, or the",
        "# public module re-exporting it); to: null = removed (hint: other definitions",
        "# of the same name, different code: to check by hand). import: the name was",
        "# a re-export of another library. proof: commit of the range that changed it.",
    ]
    for rule in rules:
        items = ", ".join(f"{key}: {_q(value)}" for key, value in rule.items())
        lines.append(f"- {{{items}}}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="odoo bare repository")
    parser.add_argument("--from", dest="from_version", required=True)
    parser.add_argument("--to", dest="to_version", required=True)
    parser.add_argument("--output", help="YAML file (default: stdout)")
    parser.add_argument("--no-proof", action="store_true", help="skip git log -S (slow)")
    args = parser.parse_args(argv)
    rules = compare(args.repo, args.from_version, args.to_version, not args.no_proof)
    text = dump(rules, args.from_version, args.to_version)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"{len(rules)} rules -> {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
