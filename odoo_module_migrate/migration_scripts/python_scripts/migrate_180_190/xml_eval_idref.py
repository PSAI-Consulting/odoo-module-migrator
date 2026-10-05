# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""XML ids used as variables in eval="..." are not available anymore in 19.0.

Source: odoo 124d945c7abc "[IMP] tools: improve idref": "if there is already
id="imd_name" declared before, eval and search can directly use the imd_name
as a variable. [...] can be simply replaced with ref="imd_name" or
ref('imd_name') [...] This commit removes the feature."

    <field name="view_id" eval="my_tree_view"/>   ->  <field name="view_id" ref="my_tree_view"/>
    eval="[(6, 0, [group_a, group_b])]"            ->  eval="[(6, 0, [ref('group_a'), ref('group_b')])]"

Only the names that are XML ids defined by the module are converted.
"""

import ast
import re

ID_RE = re.compile(r"""<(?:record|template|menuitem|report)\b[^>]*?\bid=["']([\w.]+)["']""")
EVAL_RE = re.compile(r"""\beval=(["'])(?P<value>(?:(?!\1).)*)\1""", re.S)
# names of the eval context of odoo.tools.convert (19.0 _get_eval_context)
CONTEXT_NAMES = {"Command", "time", "DateTime", "datetime", "timedelta", "relativedelta",
                 "version", "ref", "pytz", "obj", "True", "False", "None"}


def _module_ids(tools, module_path):
    ids = set()
    for path in tools.get_files(module_path, (".xml",)):
        for xid in ID_RE.findall(tools._read_content(path)):
            ids.add(xid.split(".")[-1] if "." not in xid else xid)
    return ids


def _convert_expression(value, ids):
    """New eval value, or None when nothing to convert."""
    try:
        tree = ast.parse(value.strip(), mode="eval")
    except SyntaxError:
        return None
    names = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in ids and node.id not in CONTEXT_NAMES
        and isinstance(node.ctx, ast.Load)
    ]
    if not names:
        return None
    offset = len(value) - len(value.lstrip())
    text = value
    for node in sorted(names, key=lambda n: n.col_offset, reverse=True):
        if node.lineno != 1:
            return None  # multi-line expression: not converted
        start = offset + node.col_offset
        end = offset + node.end_col_offset
        text = text[:start] + f"ref('{node.id}')" + text[end:]
    return text


def convert_eval_xml_ids(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    ids = None
    for path in tools.get_files(kwargs["module_path"], (".xml",)):
        text = tools._read_content(path)
        if "eval=" not in text:
            continue
        if ids is None:
            ids = _module_ids(tools, kwargs["module_path"])

        def replace(match):
            value = match.group("value")
            quote = match.group(1)
            if re.fullmatch(r"\s*[A-Za-z_][\w.]*\s*", value) and value.strip() in ids:
                return f"ref={quote}{value.strip()}{quote}"
            new = _convert_expression(value, ids)
            if new is None or (quote in new):
                return match.group(0)
            return f"eval={quote}{new}{quote}"

        new_text = EVAL_RE.sub(replace, text)
        if new_text != text:
            tools._write_content(path, new_text)
            logger.info("[19] XML ids used as variables in eval replaced by ref (odoo 124d945c7abc) in %s" % path)
