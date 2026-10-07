"""Targeted selectors proven by Odoo 20 sale/account view sources.

These are Odoo-standard compatibility rules, usable by every client inheriting
these core views. There are no customer names, custom XML ids or local paths.
The generic, independent XPath validator lives in analysis/views.py. A rule
must stay scoped to a proven core parent: globally renaming a field called
`state` would change unrelated models and break otherwise valid views.

Only selectors in the named parent views are rewritten; inserted fields,
labels, XML ids and translated text are preserved.
"""

import re
from lxml import etree as _etree


def migrate_view_anchors(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]

    def record(match):
        original = match[0]
        try:
            root = _etree.fromstring(original.encode())
        except _etree.XMLSyntaxError:
            return original
        parent = root.find("field[@name='inherit_id']")
        if parent is None:
            return original
        ref = parent.get("ref")

        if ref in {
            "product.product_normal_form_view",
            "product.product_template_only_form_view",
        }:
            # These product forms lost their header in Odoo 20. Content placed
            # immediately before it belongs immediately before the sheet now.
            original = re.sub(
                r"<header\b(?=[^>]*\bposition\s*=\s*(['\"])before\1)[^>]*>([\s\S]*?)</header>",
                lambda m: re.sub(r"^<header", "<sheet", m[0]).replace(
                    "</header>", "</sheet>"
                ),
                original,
            )

        def tag(m):
            value = m[0]
            if ref == "sale.view_order_form" and value.startswith("<xpath"):
                # An immediate list child became a column containing the field.
                value = re.sub(
                    r"""(list(?:\[\d+\])?/)(field)(\[@name\s*=\s*['"]price_unit['"]\])""",
                    r"\1column\3",
                    value,
                )
            if ref in {
                "account.view_invoice_tree",
                "account.view_out_invoice_tree",
                "account.view_in_invoice_tree",
            }:
                if value.startswith("<xpath"):
                    value = re.sub(
                        r"""(field\[@name\s*=\s*['"])state(['"]\])""",
                        r"\1status_in_payment\2",
                        value,
                    )
                elif re.search(r"\bposition=", value) and value.startswith("<field"):
                    value = re.sub(
                        r"""(\bname\s*=\s*['"])state(['"])""",
                        r"\1status_in_payment\2",
                        value,
                    )
            if ref in {
                "account.view_account_invoice_filter",
                "account.view_account_move_filter",
            }:
                if value.startswith("<group") and re.search(r"\bposition=", value):
                    value = re.sub(r"""\s+expand\s*=\s*(['"])0\1""", "", value)
                elif value.startswith("<xpath"):
                    value = re.sub(
                        r"""(group)\[@expand\s*=\s*['"]0['"]\]""", r"\1", value
                    )
            return value

        # Comments are not matched as tags.
        return re.sub(
            r'<!--[\s\S]*?-->|<(?:xpath|field|group)\b(?:[^>"\']|"[^"]*"|\'[^\']*\')*>',
            lambda m: m[0] if m[0].startswith("<!--") else tag(m),
            original,
        )

    for path in tools.get_files(kwargs["module_path"], (".xml",)):
        text = tools._read_content(path)
        new = re.sub(
            r"<!--[\s\S]*?-->|<record\b[^>]*>[\s\S]*?</record>",
            lambda m: m[0] if m[0].startswith("<!--") else record(m),
            text,
        )
        if new != text:
            tools._write_content(path, new)
            logger.info(
                "[20] Updated selectors against sale/account/product view sources. File %s",
                path,
            )
