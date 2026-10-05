# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""static/description/index.html must not start with an XML declaration.

Odoo parses it with lxml.html.document_fromstring(str) (odoo/addons/base/
models/ir_module.py, _apply_description_images), which raises "Unicode strings
with encoding declaration are not supported". Since 20.0 this happens during
the installation (loading.py calls module._check()), so the module does not
install anymore.
"""

import re

_XML_DECLARATION = re.compile(r"\A(﻿)?\s*<\?xml[^>]*\?>[ \t]*\n?")


def remove_description_xml_declaration(**kwargs):
    tools = kwargs["tools"]
    path = kwargs["module_path"] / "static" / "description" / "index.html"
    if not path.is_file():
        return
    content = tools._read_content(path)
    new_content = _XML_DECLARATION.sub("", content, count=1)
    if new_content != content:
        tools._write_content(path, new_content)
        kwargs["logger"].info("XML declaration removed from %s" % path)
