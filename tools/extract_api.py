# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Core API changes between two Odoo versions (used by extract_changes.py api).

Compares the *framework* (odoo/ without addons, tests, cli, upgrade_code):

* methods of BaseModel (models.py / orm/models.py) that disappear;
* public functions / classes of odoo.api, odoo.fields, odoo.tools, odoo.http
  that disappear;
* Python modules (odoo.osv...) that disappear;
* deprecation messages (warnings.warn(... deprecated ...)) of the target.

The result is a list of CANDIDATES (commented YAML): a removed name is not
always a breaking change (moved, renamed...). They are reviewed by hand before
being added to text_warnings / text_errors.
"""

import re

from extract_fields import read_blobs

CORE_RE = re.compile(r"^odoo/(?!addons/|tests/|cli/|upgrade_code/|upgrade/)(.+)\.py$")
CLASS_RE = re.compile(r"^class\s+(\w+)\b")
METHOD_RE = re.compile(r"^    def (\w+)\(")
TOP_DEF_RE = re.compile(r"^(?:def|class)\s+([A-Za-z]\w*)\b")
DEPRECATION_RE = re.compile(
    r"""warnings\.warn\(\s*(?:f?(["'])(?P<msg>(?:(?!\1).)*?[Dd]eprecat(?:(?!\1).)*)\1)""",
)


def _module_name(path):
    match = CORE_RE.match(path)
    if not match:
        return None
    name = "odoo." + match.group(1).replace("/", ".")
    return name.removesuffix(".__init__")


def core_api(repo, ref):
    files = read_blobs(repo, ref, CORE_RE)
    modules, functions, model_methods, deprecations = set(), {}, set(), []
    for path, text in files.items():
        module = _module_name(path)
        if not module:
            continue
        modules.add(module)
        current_class = None
        for lineno, line in enumerate(text.splitlines(), 1):
            match = CLASS_RE.match(line)
            if match:
                current_class = match.group(1)
            match = TOP_DEF_RE.match(line)
            if match and not line.startswith(" "):
                functions.setdefault(match.group(1), set()).add(module)
            match = METHOD_RE.match(line)
            if match and current_class == "BaseModel":
                model_methods.add(match.group(1))
        for match in DEPRECATION_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            deprecations.append((f"{path}:{line}", " ".join(match["msg"].split())))
    return modules, functions, model_methods, deprecations


def api_changes(repo, ref_from, ref_to):
    mod_a, fun_a, meth_a, _dep_a = core_api(repo, ref_from)
    mod_b, fun_b, meth_b, dep_b = core_api(repo, ref_to)
    removed_modules = sorted(m for m in mod_a - mod_b if not m.startswith("odoo._"))
    removed_methods = sorted(meth_a - meth_b)
    removed_functions = sorted(
        (name, sorted(mods)) for name, mods in fun_a.items()
        if name not in fun_b and not name.startswith("_")
        and any(m.startswith(("odoo.tools", "odoo.api", "odoo.fields", "odoo.http",
                              "odoo.models", "odoo.orm", "odoo.osv", "odoo.exceptions"))
                for m in mods)
    )
    dep_a_msgs = {msg for _loc, msg in _dep_a}
    new_deprecations = [(loc, msg) for loc, msg in dep_b if msg not in dep_a_msgs]
    return removed_modules, removed_methods, removed_functions, new_deprecations
