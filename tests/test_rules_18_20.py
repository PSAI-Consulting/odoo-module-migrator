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


def test_cron_fields_removed():
    text = (
        '        <field name="numbercall">-1</field>\n'
        '        <field name="doall" eval="False"/>\n'
        '        <field eval="False" name="doall"/>\n'
        '        <field name="active">True</field>\n'
    )
    new = _apply_yaml(f"{SCRIPTS}/text_replaces/migrate_170_180/ir_cron.yaml", ".xml", text)
    assert new == '        <field name="active">True</field>\n'


def _module_rules(step):
    import glob

    rules = []
    for path in sorted(glob.glob(f"{SCRIPTS}/deprecated_modules/{step}/*.yaml")):
        rules += yaml.safe_load(open(path, encoding="utf-8")) or []
    return rules


def test_curated_module_rules():
    from odoo_module_migrate import manifest

    cases = {
        "migrate_170_180": (
            ["account_banking_fr_lcr", "stock_picking_batch_extended_account", "sale"],
            ["account_payment_fr_lcr", "stock_picking_batch_account", "sale"],
        ),
        "migrate_190_200": (
            ["website_sale_comparison_wishlist", "pos_self_order_adyen", "hr_work_entry_holidays"],
            ["website_sale", "pos_adyen", "hr_holidays"],
        ),
    }
    for step, (depends, expected) in cases.items():
        rules = _module_rules(step)
        new, messages = manifest.apply_module_rules(depends, rules)
        assert new == expected, step
        assert all(level == "info" for level, _msg in messages), messages
        # idempotent
        assert manifest.apply_module_rules(new, rules) == (new, [])


RENAME_PY = '''from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    x_qty = fields.Float(compute="_compute_x_qty")

    @api.depends("product_uom", "location_final_id")
    def _compute_x_qty(self):
        for move in self:
            move.x_qty = move.product_uom.factor if move.location_final_id else 0


class HrLeave(models.Model):
    _inherit = "hr.leave"

    def _x(self):
        return self.holiday_status_id.name
'''

RENAME_XML = '''<odoo>
    <record id="view_move_form" model="ir.ui.view">
        <field name="model">stock.move</field>
        <field name="inherit_id" ref="stock.view_move_form"/>
        <field name="arch" type="xml">
            <field name="product_uom" position="after">
                <field name="location_final_id"/>
            </field>
        </field>
    </record>
    <record id="view_order_line" model="ir.ui.view">
        <field name="model">sale.order.line</field>
        <field name="arch" type="xml"><list><field name="product_uom_id"/></list></field>
    </record>
</odoo>
'''


def test_curated_field_renames_190_200(tmp_path):
    """Verified 19→20 renames applied where the model is known, once."""
    from odoo_module_migrate.migration_scripts.migrate_190_200 import MigrationScript

    module = tmp_path / "x_mod"
    (module / "models").mkdir(parents=True)
    (module / "views").mkdir()
    (module / "__manifest__.py").write_text("{'name': 'x', 'depends': ['stock']}")
    (module / "models" / "stock_move.py").write_text(RENAME_PY)
    (module / "views" / "views.xml").write_text(RENAME_XML)
    script = MigrationScript()
    script.parse_rules()
    script.handle_fields(module)
    py = (module / "models" / "stock_move.py").read_text()
    xml = (module / "views" / "views.xml").read_text()
    assert '@api.depends("uom_id", "forecasted_location_id")' in py
    assert "move.uom_id.factor if move.forecasted_location_id" in py
    assert "self.work_entry_type_id.name" in py
    assert '<field name="uom_id" position="after">' in xml
    assert '<field name="forecasted_location_id"/>' in xml
    # sale.order.line keeps product_uom_id in 20.0: untouched
    assert '<field name="product_uom_id"/>' in xml
    script.handle_fields(module)
    assert (module / "models" / "stock_move.py").read_text() == py
    assert (module / "views" / "views.xml").read_text() == xml
