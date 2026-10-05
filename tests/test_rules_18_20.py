# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Unit tests of the 17→18, 18→19 and 19→20 transformations."""

import re

import yaml

from odoo_module_migrate.migration_scripts.python_scripts.migrate_170_180 import (
    http_routing_helpers as hr,
)

SCRIPTS = "odoo_module_migrate/migration_scripts"


def _apply_yaml(path, ext, text):
    rules = yaml.safe_load(open(path, encoding="utf-8"))[ext]
    for pattern, repl in rules.items():
        text = re.sub(pattern, repl, text)
    return text


SLUG_PY = '''from odoo import models
from odoo.addons.http_routing.models.ir_http import slugify, url_for


class Config(models.Model):
    _name = "x.config"

    def copy(self, default=None):
        name = slugify(self.name).replace("-", "_")
        return url_for("/x/%s" % name)


def helper(value):
    return slugify(value)
'''


def test_slugify_in_methods_only():
    new, unresolved = hr._rewrite(SLUG_PY)
    assert "self.env['ir.http']._slugify(self.name)" in new
    assert "self.env['ir.http']._url_for(" in new
    # still used outside a method: import of slugify kept, url_for dropped
    assert "from odoo.addons.http_routing.models.ir_http import slugify\n" in new
    assert unresolved == [14]
    assert hr._rewrite(new) == (new, [14])


def test_slugify_import_removed():
    text = SLUG_PY.split("\n\ndef helper")[0] + "\n"
    new, unresolved = hr._rewrite(text)
    assert "http_routing" not in new
    assert not unresolved
    assert new.startswith("from odoo import models\n\n\nclass Config")


def test_api_returns_removed():
    text = (
        "    @api.returns('self', lambda value: value.id)\n"
        "    def copy(self, default=None):\n"
        "    @api.model\n"
    )
    new = _apply_yaml(f"{SCRIPTS}/text_replaces/migrate_180_190/api_returns.yaml", ".py", text)
    assert new == "    def copy(self, default=None):\n    @api.model\n"


GROUPS_XML = '''<odoo>
    <record model="ir.module.category" id="module_category_edi_worker">
        <field name="name">EDI Worker</field>
    </record>
    <record id="group_edi_worker_user" model="res.groups">
        <field name="name">User</field>
        <field name="category_id" ref="module_category_edi_worker"/>
    </record>
    <record id="group_edi_worker_manager" model="res.groups">
        <field name="name">Administrator</field>
        <field name="category_id" ref="module_category_edi_worker"/>
        <field name="implied_ids" eval="[(4, ref('group_edi_worker_user'))]"/>
    </record>
    <record id="group_technical" model="res.groups">
        <field name="name">Technical</field>
        <field name="category_id" ref="base.module_category_hidden"/>
    </record>
</odoo>
'''


def test_groups_category_to_privilege():
    from odoo_module_migrate.migration_scripts.python_scripts.migrate_180_190 import (
        groups_privilege as gp,
    )

    names = {"edi_worker.module_category_edi_worker": "EDI Worker"}
    new, created, hidden = gp._convert(GROUPS_XML, "edi_worker", names)
    assert created == ["res_groups_privilege_edi_worker"] and hidden == 1
    assert new.count('model="res.groups.privilege"') == 1
    assert new.index("res.groups.privilege") < new.index('id="group_edi_worker_user"')
    assert '<field name="name">EDI Worker</field>\n        <field name="category_id" ref="module_category_edi_worker"/>' in new
    assert new.count('<field name="privilege_id" ref="res_groups_privilege_edi_worker"/>') == 2
    assert "module_category_hidden" not in new
    assert 'name="category_id"' not in new.split("res.groups.privilege")[1].split("</record>", 1)[1]
    # idempotent
    assert gp._convert(new, "edi_worker", names) == (new, [], 0)


def test_product_storable():
    from odoo_module_migrate.migration_scripts.python_scripts.migrate_170_180 import (
        product_storable as ps,
    )

    py = (
        "moves = self.filtered(lambda m: m.product_id.type != 'product')\n"
        "if line.product_id.detailed_type == \"product\":\n"
        "domain = [('product_id.type', '=', 'product')]\n"
        "if self.type == 'product':\n"
    )
    new = ps._apply(ps.PY_RULES, py)
    assert new == (
        "moves = self.filtered(lambda m: not m.product_id.is_storable)\n"
        "if line.product_id.is_storable:\n"
        "domain = [('product_id.is_storable', '=', True)]\n"
        "if self.type == 'product':\n"          # model unknown: reported only
    )
    assert ps.LEFTOVER_RE.search(new)
    xml = '''<record id="v" model="ir.ui.view">
        <field name="model">product.product</field>
        <field name="arch" type="xml">
            <field name="virtual_free_qty" invisible="type != 'product'"/>
        </field>
    </record>
    <record id="w" model="ir.ui.view">
        <field name="model">stock.picking.type</field>
        <field name="arch" type="xml"><field name="x" invisible="type != 'product'"/></field>
    </record>'''
    new = ps.PRODUCT_VIEW_RE.sub(lambda m: ps._apply(ps.VIEW_RULES, m.group(0)), xml)
    assert 'invisible="not is_storable"' in new
    assert new.count("type != 'product'") == 1  # other model untouched


def test_odoo_models_imports():
    from odoo_module_migrate.migration_scripts.python_scripts.migrate_180_190 import (
        odoo_models_imports as omi,
    )

    text = "from odoo.models import Model, api\nfrom odoo.models import AccessError\nfrom odoo import models\n"
    new, reported = omi._rewrite(text)
    assert new == (
        "from odoo import api\nfrom odoo.models import Model\n"
        "from odoo.models import AccessError\nfrom odoo import models\n"
    )
    assert reported == [(2, "AccessError")]
    assert omi._rewrite(new)[0] == new


def test_view_type_list_target_inline_t_esc():
    view = '<record id="v" model="ir.ui.view">\n    <field name="type">tree</field>\n'
    assert _apply_yaml(f"{SCRIPTS}/text_replaces/migrate_170_180/view_type_list.yaml", ".xml", view) == (
        '<record id="v" model="ir.ui.view">\n    <field name="type">list</field>\n'
    )
    action = '        <field name="view_mode">form</field>\n        <field name="target">inline</field>\n'
    assert _apply_yaml(f"{SCRIPTS}/text_replaces/migrate_180_190/act_window_target_inline.yaml", ".xml", action) == (
        '        <field name="view_mode">form</field>\n'
    )
    kanban = '<span><t t-esc="record.name.value"/></span>'
    once = _apply_yaml(f"{SCRIPTS}/text_replaces/migrate_190_200/qweb_t_esc.yaml", ".xml", kanban)
    assert once == '<span><t t-out="record.name.value"/></span>'
    assert _apply_yaml(f"{SCRIPTS}/text_replaces/migrate_190_200/qweb_t_esc.yaml", ".xml", once) == once


def test_eval_xml_ids(tmp_path):
    import logging

    from odoo_module_migrate import tools
    from odoo_module_migrate.migration_scripts.python_scripts.migrate_180_190 import (
        xml_eval_idref as xe,
    )

    module = tmp_path / "m"
    (module / "views").mkdir(parents=True)
    path = module / "views" / "v.xml"
    path.write_text(
        '<odoo>\n<record id="my_tree" model="ir.ui.view"/>\n<record id="group_a" model="res.groups"/>\n'
        '<record id="act" model="ir.actions.act_window">\n'
        '  <field name="view_id" eval="my_tree"/>\n'
        '  <field name="group_ids" eval="[(6, 0, [group_a, ref(\'base.group_user\')])]"/>\n'
        '  <field name="active" eval="True"/>\n'
        '  <field name="date" eval="(DateTime.today()).strftime(\'%Y-%m-%d\')"/>\n'
        '</record>\n</odoo>\n',
        encoding="utf-8",
    )
    xe.convert_eval_xml_ids(tools=tools, logger=logging.getLogger("t"), module_path=module)
    text = path.read_text(encoding="utf-8")
    assert '<field name="view_id" ref="my_tree"/>' in text
    assert "eval=\"[(6, 0, [ref('group_a'), ref('base.group_user')])]\"" in text
    assert '<field name="active" eval="True"/>' in text
    assert "DateTime.today()" in text
    before = text
    xe.convert_eval_xml_ids(tools=tools, logger=logging.getLogger("t"), module_path=module)
    assert path.read_text(encoding="utf-8") == before


def test_cron_fields_removed():
    text = (
        '        <field name="numbercall">-1</field>\n'
        '        <field name="doall" eval="False"/>\n'
        '        <field eval="False" name="doall"/>\n'
        '        <field name="active">True</field>\n'
    )
    new = _apply_yaml(f"{SCRIPTS}/text_replaces/migrate_170_180/ir_cron.yaml", ".xml", text)
    assert new == '        <field name="active">True</field>\n'
