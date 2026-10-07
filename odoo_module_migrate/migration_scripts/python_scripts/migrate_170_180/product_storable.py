# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Product type 'product' (storable) became type 'consu' + is_storable in 18.0.

Source: odoo commit 728d9f83f6d1 "[REF] stock: remove product type", whose
diff gives the replacements used here:
    move.product_id.type != 'product'        -> not move.product_id.is_storable
    move.product_id.detailed_type == 'product' -> move.product_id.is_storable
    invisible="type != 'product'"            -> invisible="not is_storable"
and detailed_type was merged back into type.

Only the places where the model is certain are rewritten:
* attribute chains ending with product_id / product_tmpl_id (Python and XML);
* domains on 'product_id.type' / 'product_tmpl_id.type';
* expressions of the views of product.template / product.product.
Other comparisons with 'product' are reported.
"""

import re

CHAIN = r"(?P<chain>[A-Za-z_][\w.]*\.(?:product_id|product_tmpl_id))"
PY_RULES = [
    (
        re.compile(CHAIN + r"\.(?:detailed_)?type\s*!=\s*(['\"])product\2"),
        r"not \g<chain>.is_storable",
    ),
    (
        re.compile(CHAIN + r"\.(?:detailed_)?type\s*==\s*(['\"])product\2"),
        r"\g<chain>.is_storable",
    ),
    (
        re.compile(
            r"""(?P<q>['"])(?P<f>product_id|product_tmpl_id)\.(?:detailed_)?type(?P=q)\s*,\s*(?P<q2>['"])=(?P=q2)\s*,\s*(?P<q3>['"])product(?P=q3)"""
        ),
        r"\g<q>\g<f>.is_storable\g<q>, \g<q2>=\g<q2>, True",
    ),
]
# expressions inside views of product.template / product.product
VIEW_RULES = [
    (
        re.compile(r"\b(?:detailed_)?type\s*!=\s*(?P<q>['\"]|&quot;)product(?P=q)"),
        "not is_storable",
    ),
    (
        re.compile(r"\b(?:detailed_)?type\s*==\s*(?P<q>['\"]|&quot;)product(?P=q)"),
        "is_storable",
    ),
    # A storable product and a consumable now both have type='consu'.
    (
        re.compile(r"\bdetailed_type\s*==\s*(?P<q>['\"]|&quot;)consu(?P=q)"),
        "type == 'consu' and not is_storable",
    ),
    (
        re.compile(r"\bdetailed_type\s*!=\s*(?P<q>['\"]|&quot;)consu(?P=q)"),
        "(type != 'consu' or is_storable)",
    ),
    (re.compile(r"\bdetailed_type\b"), "type"),
    (re.compile(r"""(['"])detailed_type\1"""), r"\1type\1"),
]
PRODUCT_VIEW_RE = re.compile(
    r"""<record\b(?=[^>]*\bmodel=["']ir\.ui\.view["'])[^>]*>(?:(?!</record>).)*?"""
    r"""<field\s+name=["']model["']\s*>\s*product\.(?:template|product)\s*</field>.*?</record>""",
    re.S,
)
LEFTOVER_RE = re.compile(
    r"""\b(?:detailed_)?type['"]?\s*(?:[!=]=|,\s*['"]=['"]\s*,)\s*['"]product['"]"""
)
DETAILED_TYPE_RE = re.compile(r"\bdetailed_type\b")


def _apply(rules, text):
    for pattern, repl in rules:
        text = pattern.sub(repl, text)
    return text


def migrate_product_storable(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py", ".xml")):
        text = tools._read_content(path)
        if "product" not in text or "type" not in text:
            continue
        new = _apply(PY_RULES, text)
        if path.suffix == ".xml":
            new = PRODUCT_VIEW_RE.sub(lambda m: _apply(VIEW_RULES, m.group(0)), new)
        if new != text:
            tools._write_content(path, new)
            logger.info("[18] product type 'product' -> is_storable in %s" % path)
        for match in LEFTOVER_RE.finditer(new):
            line = new.count("\n", 0, match.start()) + 1
            logger.warning(
                "[18] Product type 'product' does not exist anymore: use type 'consu' and"
                " is_storable (odoo 728d9f83f6d1), if this is a product. File %s:%s"
                % (path, line)
            )
        if path.suffix == ".xml":
            for record in PRODUCT_VIEW_RE.finditer(new):
                for match in DETAILED_TYPE_RE.finditer(record.group(0)):
                    line = new.count("\n", 0, record.start() + match.start()) + 1
                    logger.error(
                        "[18] detailed_type no longer exists on products; replace it with type"
                        " and is_storable according to the old value. File %s:%s"
                        % (path, line)
                    )
