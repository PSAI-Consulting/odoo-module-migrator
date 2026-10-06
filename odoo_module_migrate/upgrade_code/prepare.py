# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Prepare modules so that Odoo's official upgrade_code scripts see everything.

19.4-00-ir-access.py only reads the data files whose path contains 'security'
or 'access' (``extract()``): ir.rule / ir.model.access records declared in
another file (e.g. views/*.xml) would be silently left as is, and the module
would not install on 20.0 (these models do not exist anymore).

They are moved to ``security/<module>_access_moved.xml``, declared in the
manifest at the place of the file they come from (same load order, same xmlids).
"""

import ast
import re

from .. import manifest as manifest_tools
from ..log import logger
from ..tools import _read_content, _write_content

ACCESS_RECORD_RE = re.compile(
    r"""[ \t]*<record\b(?=[^>]*\bmodel=["']ir\.(?:rule|model\.access)["'])[^>]*>.*?</record>[ \t]*\n?""",
    re.S,
)
DATA_NOUPDATE_RE = re.compile(r"""<data\b[^>]*noupdate=["'](?:1|True)["']""")


def _data_files(text):
    node = manifest_tools._find_key(text, "data")
    try:
        return list(ast.literal_eval(node)) if node is not None else []
    except ValueError:
        return []


def move_access_records(module_path):
    """Return the list of files the records were moved from."""
    manifest_path = module_path / "__manifest__.py"
    if not manifest_path.exists():
        return []
    manifest_text = _read_content(manifest_path)
    data = _data_files(manifest_text)
    moved_from, records = [], []
    for name in data:
        if not name.endswith(".xml") or "security" in name or "access" in name:
            continue
        path = module_path / name
        if not path.is_file():
            continue
        text = _read_content(path)
        found = ACCESS_RECORD_RE.findall(text)
        if not found:
            continue
        noupdate = bool(DATA_NOUPDATE_RE.search(text))
        records.append((name, noupdate, found))
        _write_content(path, ACCESS_RECORD_RE.sub("", text))
        moved_from.append(name)
    if not records:
        return []

    target = f"security/{module_path.name}_access_moved.xml"
    body = []
    for name, noupdate, found in records:
        body.append(f"    <!-- moved from {name} -->\n")
        if noupdate:
            body.append('    <data noupdate="1">\n')
        body.extend(r if r.endswith("\n") else r + "\n" for r in found)
        if noupdate:
            body.append("    </data>\n")
    content = '<?xml version="1.0" encoding="utf-8"?>\n<odoo>\n' + "".join(body) + "</odoo>\n"
    _write_content(module_path / target, content)

    # declare the new file just before the first file it comes from
    node = manifest_tools._find_key(manifest_text, "data")
    pos = manifest_tools._Positions(manifest_text)
    elt = node.elts[data.index(moved_from[0])]
    quote = manifest_text[pos(elt.lineno, elt.col_offset)]
    insert_at = pos(elt.lineno, elt.col_offset)
    line_start = manifest_text.rfind("\n", 0, insert_at) + 1
    indent = manifest_text[line_start:insert_at]
    if indent.strip():  # one-line list
        entry = f"{quote}{target}{quote}, "
    else:
        entry = f"{quote}{target}{quote},\n{indent}"
    _write_content(manifest_path, manifest_text[:insert_at] + entry + manifest_text[insert_at:])
    logger.info(
        "ir.rule / ir.model.access records moved from %s to %s so that Odoo's"
        " 19.4-00-ir-access converts them" % (", ".join(moved_from), target)
    )
    return moved_from


# <record model="ir.rule">, <function model="ir.rule">, <value model="ir.rule">...
ACCESS_MODEL_RE = re.compile(r"""\bmodel=["']ir\.(?:model\.access|rule)["']""")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
ACCESS_LEFT_MESSAGE = (
    "[20] ir.model.access / ir.rule record left in XML: models removed in 20.0, rewrite it"
    " as ir.access (with --odoo-root, Odoo's 19.4-00-ir-access converts the others; the ones"
    " left usually modify an access of another module)"
)


def access_records_left(module_path):
    """(xml file, first line) of the XML files of the module still using the
    ir.rule / ir.model.access models, once every conversion is done (the
    records converted by 19.4-00-ir-access.py or by the fallback are gone)."""
    manifest_path = module_path / "__manifest__.py"
    if not manifest_path.exists():
        return []
    try:
        manifest = ast.literal_eval(_read_content(manifest_path).lstrip())
    except (ValueError, SyntaxError):
        return []
    result = []
    for name in manifest.get("data", []) + manifest.get("demo", []):
        path = module_path / name
        if not name.endswith(".xml") or not path.is_file():
            continue  # only the loaded files matter
        text = _read_content(path)
        # commented out records are not loaded
        text = COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
        match = ACCESS_MODEL_RE.search(text)
        if match:
            result.append((path, text.count("\n", 0, match.start()) + 1))
    return result
