# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Unit tests of the 17→18, 18→19 and 19→20 transformations."""

import re

import pytest
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


def test_rejected_candidates_reported_190_200(tmp_path, caplog):
    """A rename candidate rejected after review (scale changed) is reported as
    removed with its probable replacement, never renamed."""
    import logging

    from odoo_module_migrate.migration_scripts.migrate_190_200 import MigrationScript

    module = tmp_path / "x_mod"
    module.mkdir()
    (module / "__manifest__.py").write_text("{'name': 'x', 'depends': ['account']}")
    (module / "models.py").write_text(
        "from odoo import models\n\n\nclass AccountMoveLine(models.Model):\n"
        "    _inherit = 'account.move.line'\n\n    def _x(self):\n        return self.deductible_amount\n"
    )
    script = MigrationScript()
    script.parse_rules()
    with caplog.at_level(logging.WARNING):
        script.handle_fields(module)
    assert "self.deductible_amount" in (module / "models.py").read_text()
    assert any(
        "account.move.line.deductible_amount was removed" in r.getMessage()
        and "deductible_percentage" in r.getMessage()
        for r in caplog.records
    )


def test_core_api_replaces_190_200():
    path = f"{SCRIPTS}/text_replaces/migrate_190_200/core_api.yaml"
    text = (
        "records = self._filter_access_rules('read')\n"
        "records = self._filter_access_rules_python('write')\n"
        "self.check_access_rule('unlink')\n"
        "amount = fields.Float(group_operator='sum')\n"
        "from odoo.tools import test_reports\n"
        "odoo.tools.test_reports.try_report(cr, uid, 'x', ids)\n"
        "    from odoo.tests.common import Form\n"
        "if not self._check_recursion():\n"
    )
    new = _apply_yaml(path, ".py", text)
    assert new == (
        "records = self._filtered_access('read')\n"
        "records = self._filtered_access('write')\n"
        "self.check_access('unlink')\n"
        "amount = fields.Float(aggregator='sum')\n"
        "from odoo.tests import reports as test_reports\n"
        "odoo.tests.reports.try_report(cr, uid, 'x', ids)\n"
        "    from odoo.tests import Form\n"
        "if self._has_cycle():\n"
    )
    assert _apply_yaml(path, ".py", new) == new


def test_core_api_errors_190_200():
    rules = yaml.safe_load(open(f"{SCRIPTS}/text_errors/migrate_190_200/core_api.yaml", encoding="utf-8"))[".py"]

    def hits(text):
        return [p for p in rules if re.search(p, text)]

    assert hits("self.env['x'].check_access_rights('read', raise_exception=False)")
    assert hits("from odoo.tools import ustr, html_escape")
    assert hits("create_unique_index(cr, 'idx', 'tbl', ['a'])")
    # no false positive on look-alike names
    assert not hits("def flatten(self, items):\n    return my_flatten(items)\n")
    assert not hits("self.check_access('read')\nself.has_access('write')\n")


def test_user_has_groups_170_180():
    path = f"{SCRIPTS}/text_replaces/migrate_170_180/core_api.yaml"
    text = "if self.user_has_groups('base.group_user'):\n    rec.sudo().user_has_groups('x.g,!x.h')\n"
    new = _apply_yaml(path, ".py", text)
    # self.user_has_groups: left to replace_user_has_groups (has_group for one group)
    assert new == ("if self.user_has_groups('base.group_user'):\n"
                   "    rec.sudo().env.user.has_groups('x.g,!x.h')\n")
    assert _apply_yaml(path, ".py", new) == new


def test_model_rules_190_200(tmp_path, caplog):
    import logging

    from odoo_module_migrate.migration_scripts.migrate_190_200 import MigrationScript

    script = MigrationScript()
    script.parse_rules()
    path = tmp_path / "models.py"
    path.write_text(
        "types = self.env['hr.contract.type'].search([])\n"
        "other = self.env['hr.contract.type.x']\n"
        "scraps = self.env['stock.scrap']\n"
    )
    with caplog.at_level(logging.WARNING):
        script.process_file(str(tmp_path), "models.py", ".py", {}, tmp_path, False)
    text = path.read_text()
    assert "self.env['hr.employee.type'].search([])" in text
    assert "'hr.contract.type.x'" in text
    # curated message wins over the generated one
    assert any("stock.scrap" in r.getMessage() and "stock.move records" in r.getMessage()
               for r in caplog.records)
    script.process_file(str(tmp_path), "models.py", ".py", {}, tmp_path, False)
    assert path.read_text() == text


def test_product_type_warning_170_180():
    rules = yaml.safe_load(open(f"{SCRIPTS}/text_warnings/migrate_170_180/product_type.yaml", encoding="utf-8"))
    assert any(re.search(p, '{"name": "x", "type": "product"}') for p in rules[".py"])
    assert not any(re.search(p, '{"display_type": "product", "type": "consu"}') for p in rules[".py"])
    assert any(re.search(p, '<field name="type">product</field>') for p in rules[".xml"])
    assert not any(re.search(p, '<field name="type">consu</field>') for p in rules[".xml"])


def test_curated_field_renames_170_180(tmp_path):
    from odoo_module_migrate.migration_scripts.migrate_170_180 import MigrationScript

    module = tmp_path / "x_mod"
    (module / "views").mkdir(parents=True)
    (module / "__manifest__.py").write_text("{'name': 'x', 'depends': ['point_of_sale']}")
    (module / "views" / "views.xml").write_text(
        '<odoo><record id="v" model="ir.ui.view"><field name="model">pos.config</field>'
        '<field name="arch" type="xml"><field name="iface_customer_facing_display_background_image_1920"/>'
        '</field></record></odoo>'
    )
    script = MigrationScript()
    script.parse_rules()
    script.handle_fields(module)
    xml = (module / "views" / "views.xml").read_text()
    assert '<field name="customer_display_bg_img"/>' in xml
    script.handle_fields(module)
    assert (module / "views" / "views.xml").read_text() == xml


def test_js_and_view_rules_190_200_no_false_positive():
    """Generated JS / view rules: imports and views still present in 20.0
    are never reported, rewrites are idempotent."""
    errors = yaml.safe_load(open(f"{SCRIPTS}/text_errors/migrate_190_200/js_modules.yaml", encoding="utf-8"))
    replaces = yaml.safe_load(open(f"{SCRIPTS}/text_replaces/migrate_190_200/js_modules.yaml", encoding="utf-8"))
    views = yaml.safe_load(open(f"{SCRIPTS}/text_errors/migrate_190_200/views.yaml", encoding="utf-8"))
    js = (
        'import { registry } from "@web/core/registry";\n'
        "import { useService } from '@web/core/utils/hooks';\n"
        'import { FormController } from "@web/views/form/form_controller";\n'
        'import { _t } from "@web/core/l10n/translation";\n'
        'import { rpc } from "@web/core/network/rpc";\n'
    )
    assert not [p for p in errors[".js"] if re.search(p, js)]
    for pattern, repl in replaces[".js"].items():
        assert re.sub(pattern, repl, js) == js
    xml = '<field name="inherit_id" ref="sale.view_order_form"/>\n<template inherit_id="web.layout"/>\n'
    assert not [p for p in views[".xml"] if re.search(p, xml)]
    # a moved module is rewritten once
    old = next(iter(replaces[".js"]))
    sample = re.sub(r"\(\[\\\"'\]\)(.*)\\1", r'"\1"', old).replace("\\", "")
    new = sample
    for pattern, repl in replaces[".js"].items():
        new = re.sub(pattern, repl, new)
    assert new != sample
    again = new
    for pattern, repl in replaces[".js"].items():
        again = re.sub(pattern, repl, again)
    assert again == new


def test_curated_field_renames_180_190(tmp_path):
    from odoo_module_migrate.migration_scripts.migrate_180_190 import MigrationScript

    module = tmp_path / "x_mod"
    module.mkdir()
    (module / "__manifest__.py").write_text("{'name': 'x', 'depends': ['sale']}")
    (module / "models.py").write_text(
        "from odoo import api, models\n\n\nclass SaleReport(models.Model):\n"
        "    _inherit = 'sale.report'\n\n    @api.depends('product_uom')\n"
        "    def _x(self):\n        return self.product_uom\n"
    )
    script = MigrationScript()
    script.parse_rules()
    script.handle_fields(module)
    py = (module / "models.py").read_text()
    assert "@api.depends('product_uom_id')" in py and "return self.product_uom_id" in py
    script.handle_fields(module)
    assert (module / "models.py").read_text() == py


@pytest.mark.parametrize("step", ["migrate_170_180", "migrate_180_190"])
def test_js_and_view_rules_no_false_positive(step):
    errors = yaml.safe_load(open(f"{SCRIPTS}/text_errors/{step}/js_modules.yaml", encoding="utf-8"))
    views = yaml.safe_load(open(f"{SCRIPTS}/text_errors/{step}/views.yaml", encoding="utf-8"))
    js = ('import { registry } from "@web/core/registry";\n'
          'import { useService } from "@web/core/utils/hooks";\n'
          'import { _t } from "@web/core/l10n/translation";\n')
    assert not [p for p in errors[".js"] if re.search(p, js)]
    xml = '<field name="inherit_id" ref="sale.view_order_form"/>\n'
    assert not [p for p in views[".xml"] if re.search(p, xml)]


def test_access_records_left_to_upgrade_code():
    """ir.rule / ir.model.access in data files: converted by Odoo's official
    script when it runs, still reported in Python code."""
    from odoo_module_migrate import tools
    from odoo_module_migrate.migration_scripts.migrate_190_200 import MigrationScript

    script = MigrationScript()
    script.parse_rules()
    tools.RUN_CONTEXT["upgrade_code"] = True
    try:
        xml = script._file_rules(".xml")["errors"]
        py = script._file_rules(".py")["errors"]
    finally:
        tools.RUN_CONTEXT.clear()
    assert not any(r"ir\.rule" in p or r"ir\.model\.access" in p for p in xml)
    assert any(r"ir\.model\.access" in p for p in py)
    assert any(r"account\.group" in p for p in xml)  # 19.3-00-account-groups.py is not run


def test_auto_added_fields_notice_only_from_17():
    """Fields used by view expressions are added automatically since 18.0
    (odoo 6f06420e4a94, not in 17.0): an 18.0 module already works so, the
    notice is not repeated by the 18.0 -> 19.0 step."""
    from odoo_module_migrate.migration_scripts.migrate_170_180 import MigrationScript as M18
    from odoo_module_migrate.migration_scripts.migrate_180_190 import MigrationScript as M19

    def warnings(script_class):
        script = script_class()
        script.parse_rules()
        return script._file_rules(".xml")["warnings"]

    assert any("137031" in m for m in warnings(M18).values())
    assert not any("137031" in m for m in warnings(M19).values())
