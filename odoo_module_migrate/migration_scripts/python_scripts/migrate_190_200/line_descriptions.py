"""Warn about Odoo 20 line descriptions that no longer include product names."""

import re


QWEB_ATTRIBUTE_RE = re.compile(
    r"\b(?:t-field|t-esc|t-out|t-value|t-if|t-elif)\s*=\s*(['\"])(.*?)\1",
    re.S,
)
LINE_NAME_RE = re.compile(
    r"\b(?:[A-Za-z_]\w*\.)*(?:line|order_line|sale_line|purchase_line|invoice_line)\.name\b"
)


def check_line_descriptions(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".xml",)):
        text = tools._read_content(path)
        for attribute in QWEB_ATTRIBUTE_RE.finditer(text):
            if not LINE_NAME_RE.search(attribute.group(2)):
                continue
            line = text.count("\n", 0, attribute.start()) + 1
            logger.warning(
                "[20] A sale, purchase or invoice line .name no longer includes the"
                " product name; use product_id.display_name when the product label is"
                " required (odoo c5037bbe0789). File %s:%s",
                path,
                line,
            )
