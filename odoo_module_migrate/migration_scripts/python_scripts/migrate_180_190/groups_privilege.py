# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""res.groups.category_id was replaced by privilege_id in 19.0.

Sources:
* OpenUpgrade 19.0 base/19.0.1.3/upgrade_analysis.txt: res.groups category_id
  DEL, privilege_id NEW (relation res.groups.privilege), res.groups.privilege
  category_id NEW (relation ir.module.category);
* odoo 19.0 addons/stock/security/stock_security.xml: groups of
  base.module_category_hidden simply lost their category_id;
* OCA queue 19.0 queue_job/security/security.xml: a res.groups.privilege
  record per former category, referenced by privilege_id.

    <record id="group_x" model="res.groups">
        <field name="category_id" ref="module_category_x"/>
->
    <record id="res_groups_privilege_x" model="res.groups.privilege">
        <field name="name">X</field>
        <field name="category_id" ref="module_category_x"/>
    </record>
    <record id="group_x" model="res.groups">
        <field name="privilege_id" ref="res_groups_privilege_x"/>
"""

import re

HIDDEN = {"base.module_category_hidden"}
GROUP_RECORD_RE = re.compile(
    r"""(?P<indent>[ \t]*)<record\b(?=[^>]*\bmodel=["']res\.groups["'])[^>]*>.*?</record>""", re.S
)
CATEGORY_FIELD_RE = re.compile(
    r"""(?P<indent>[ \t]*)<field\s+name=["']category_id["']\s+ref=["'](?P<ref>[\w.]+)["']\s*/>[ \t]*\n?"""
)
CATEGORY_RECORD_RE = re.compile(
    r"""<record\b(?=[^>]*\bmodel=["']ir\.module\.category["'])(?=[^>]*\bid=["'](?P<id>[\w.]+)["'])[^>]*>(?P<body>.*?)</record>""",
    re.S,
)
NAME_FIELD_RE = re.compile(r"""<field\s+name=["']name["']\s*>(?P<name>[^<]+)</field>""")


def _privilege_id(ref):
    local = ref.split(".")[-1]
    return "res_groups_privilege_" + local.removeprefix("module_category_")


def _category_names(tools, module_path, module_name):
    names = {}
    for path in tools.get_files(module_path, (".xml",)):
        for match in CATEGORY_RECORD_RE.finditer(tools._read_content(path)):
            name = NAME_FIELD_RE.search(match["body"])
            if name:
                xid = match["id"] if "." in match["id"] else f"{module_name}.{match['id']}"
                names[xid] = name["name"].strip()
    return names


def _humanize(ref):
    words = ref.split(".")[-1].removeprefix("module_category_").replace("_", " ")
    return words.strip().title() or ref


def _convert(text, module_name, category_names):
    """Return (new_text, created privilege ids, hidden groups count)."""
    created = {}
    hidden = 0
    out, last = [], 0
    for record in GROUP_RECORD_RE.finditer(text):
        body = record.group(0)
        match = CATEGORY_FIELD_RE.search(body)
        if not match:
            continue
        ref = match["ref"]
        full_ref = ref if "." in ref else f"{module_name}.{ref}"
        if full_ref in HIDDEN:
            new_body = body[:match.start()] + body[match.end():]
            hidden += 1
        else:
            privilege = _privilege_id(ref)
            new_field = f'{match["indent"]}<field name="privilege_id" ref="{privilege}"/>\n'
            new_body = body[:match.start()] + new_field + body[match.end():]
            if privilege not in created and not re.search(
                rf"""\bid=["']{re.escape(privilege)}["']""", text
            ):
                indent = record["indent"]
                name = category_names.get(full_ref) or _humanize(ref)
                created[privilege] = (
                    f'{indent}<record id="{privilege}" model="res.groups.privilege">\n'
                    f'{indent}    <field name="name">{name}</field>\n'
                    f'{indent}    <field name="category_id" ref="{ref}"/>\n'
                    f"{indent}</record>\n"
                )
                out.append(text[last:record.start()])
                out.append(created[privilege])
                last = record.start()
        out.append(text[last:record.start()])
        out.append(new_body)
        last = record.end()
    out.append(text[last:])
    return "".join(out), list(created), hidden


def convert_groups_category_to_privilege(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    module_path, module_name = kwargs["module_path"], kwargs["module_name"]
    names = None
    for path in tools.get_files(module_path, (".xml",)):
        text = tools._read_content(path)
        if "res.groups" not in text or "category_id" not in text:
            continue
        if names is None:
            names = _category_names(tools, module_path, module_name)
        new_text, created, hidden = _convert(text, module_name, names)
        if new_text != text:
            tools._write_content(path, new_text)
            logger.info(
                "[19] res.groups category_id -> privilege_id in %s (%d privilege(s) created,"
                " %d hidden group(s)): check the privilege names" % (path, len(created), hidden)
            )
