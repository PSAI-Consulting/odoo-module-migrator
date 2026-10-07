import ast
from lxml import etree as _etree


def check_invisible_fields(**kwargs):
    for path in kwargs["tools"].get_files(kwargs["module_path"], (".xml",)):
        try:
            root = _etree.parse(str(path))
        except _etree.XMLSyntaxError:
            continue
        for arch in root.xpath("//record[@model='ir.ui.view']/field[@name='arch']"):
            used = set()
            for node in arch.iter():
                if not isinstance(node.tag, str):
                    continue
                for attr in (
                    "invisible",
                    "column_invisible",
                    "readonly",
                    "required",
                    "domain",
                    "context",
                ):
                    try:
                        expr = ast.parse(node.get(attr) or "", mode="eval")
                    except SyntaxError:
                        continue
                    used.update(n.id for n in ast.walk(expr) if isinstance(n, ast.Name))
            for node in arch.iter("field"):
                if node.get("invisible") not in ("1", "True", "true"):
                    continue
                name = node.get("name")
                if name in used:
                    kwargs["logger"].warning(
                        "[18] Invisible field %s is used by an expression; Odoo can add it automatically. Review before removal (odoo PR 137031). File %s:%s",
                        name,
                        path,
                        node.sourceline,
                    )
