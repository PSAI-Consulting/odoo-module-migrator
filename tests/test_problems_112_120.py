# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Regressions of PROBLEMES_RENCONTRES.md 112 to 120 (Stof / OCA 17 -> 20)."""

import logging
import re

from odoo_module_migrate import tools
from odoo_module_migrate.analysis import models, python_checks
from odoo_module_migrate.migration_rules import loader
from odoo_module_migrate.migration_scripts.migrate_190_200 import _sanitize_acl_files
from odoo_module_migrate.migration_scripts.python_scripts.migrate_190_200.decimal_precisions import (
    migrate_renamed_decimal_precisions,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_190_200.table_query import (
    _convert,
)

LOGGER = logging.getLogger("odoo_module_migrate")


def addon(root, name, depends=(), code=""):
    path = root / name
    path.mkdir(parents=True)
    (path / "__manifest__.py").write_text(repr({"name": name, "depends": list(depends), "data": []}), encoding="utf-8")
    (path / "models.py").write_text(code, encoding="utf-8")
    return path


def messages(module, index):
    return [issue[-1] for issue in python_checks.check_module(module, index)]


def test_112_field_read_by_the_module_own_mixin_is_not_an_error(tmp_path):
    addon(tmp_path, "base", code="class B(Model):\n    _name = 'base'\n")
    mod = addon(tmp_path, "barcodes_generator_abstract", ["base"], """class Mixin(AbstractModel):
    _name = 'barcode.generate.mixin'
    def generate(self):
        return self.barcode
""")
    index = models.ModelIndex.build([tmp_path])
    assert not [m for m in messages(mod, index) if "barcode.generate.mixin.barcode" in m]


def test_113_dict_key_renamed_as_a_whole_token(tmp_path):
    addon(tmp_path, "stock", code="""class Move(Model):
    _name = 'stock.move'
    uom_id = fields.Many2one('uom.uom')
    product_id = fields.Many2one('product.product')
    product_uom_qty = fields.Float()
    location_id = fields.Many2one('stock.location')
""")
    mod = addon(tmp_path, "stock_available", ["stock"], """class T(TransactionCase):
    def test(self):
        self.env['stock.move'].create({
            "product_id": productA.id,
            "product_uom": productA.uom_id.id,
            "product_uom_qty": 1,
            "location_id": loc.id,
        })
""")
    index = models.ModelIndex.build([tmp_path])
    python_checks.apply_field_renames(mod, index, {("stock.move", "product_uom"): "uom_id"})
    text = (mod / "models.py").read_text(encoding="utf-8")
    compile(text, "models.py", "exec")
    assert '"uom_id": productA.uom_id.id,' in text and "ductA" not in text.replace("productA", "")


def test_113_decimal_precision_renamed_in_19_is_converted_from_19(tmp_path):
    mod = addon(tmp_path, "stock_available", code='qty = fields.Float(digits="Product Unit of Measure")\n')
    migrate_renamed_decimal_precisions(module_path=mod, tools=tools, logger=LOGGER)
    assert 'digits="Product Unit"' in (mod / "models.py").read_text(encoding="utf-8")


def test_114_compute_override_calling_super_keeps_target_dependencies(tmp_path):
    addon(tmp_path, "base", code="class B(Model):\n    _name = 'base'\n")
    addon(tmp_path, "sale", ["base"], """class SO(Model):
    _name = 'sale.order'
    @api.depends('state', 'order_line.invoice_status')
    def _compute_invoice_status(self):
        pass
""")
    mod = addon(tmp_path, "sale_force_invoiced", ["sale"], """class SO(Model):
    _inherit = 'sale.order'
    @api.depends('force_invoiced')
    def _compute_invoice_status(self):
        res = super()._compute_invoice_status()
        return res
""")
    index = models.ModelIndex.build([tmp_path])
    assert not [m for m in messages(mod, index) if "different @api.depends" in m]


def test_115_super_call_with_a_removed_keyword_of_a_base_model_method(tmp_path):
    addon(tmp_path, "base", code="""class P(Model):
    _name = 'res.partner'
    def _display_address(self, without_name=False, separator='\\n'):
        return ''
""")
    mod = addon(tmp_path, "partner_address_street3", ["base"], """class P(Model):
    _inherit = 'res.partner'
    def _display_address(self, without_company=False):
        return super()._display_address(without_company=without_company)
""")
    index = models.ModelIndex.build([tmp_path])
    found = [m for m in messages(mod, index) if "_display_address" in m]
    assert found and "removed keyword(s) without_company" in found[0]


def test_116_and_119_create_keys_through_self_attributes_and_env_company(tmp_path):
    addon(tmp_path, "base", code="""class P(Model):
    _name = 'res.partner'
    name = fields.Char()
    is_company = fields.Boolean()
class C(Model):
    _name = 'res.company'
    name = fields.Char()
""")
    mod = addon(tmp_path, "partner_contact_access_link", ["base"], """class P(Model):
    _inherit = 'res.partner'
    def check(self):
        company = self.env.company
        return company.company_registry
""")
    # as in the OCA module: the removed field is used by a test file
    (mod / "tests").mkdir()
    (mod / "tests" / "test_link.py").write_text("""class T(TransactionCase):
    def setUp(self):
        super().setUp()
        self.partner_model = self.env["res.partner"]
        self.company = self.partner_model.create({"name": "C", "company_type": "company"})
""", encoding="utf-8")
    (mod / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    index = models.ModelIndex.build([tmp_path])
    found = messages(mod, index)
    assert any("res.partner.company_type does not exist" in m for m in found)
    assert any("res.company.company_registry does not exist" in m for m in found)


def test_117_group_operator_renamed_as_a_call_argument_only():
    for step in ("migrate_170_180", "migrate_190_200"):
        path = loader.SCRIPTS_DIR / "text_replaces" / step / "core_api.yaml"
        rules = loader.load_file(path, "text_replaces").document[".py"]
        pattern = next(key for key in rules if "group_operator" in key)
        source = (
            'group_operator = fields.Selection([("sum", "Sum")])\n'
            'amount = fields.Float(group_operator="sum")\n'
            'total = fields.Float(\n    string="T",\n    group_operator = "avg",\n)\n'
            'if self.group_operator == "sum": rec.group_operator = "avg"\n'
        )
        result = re.sub(pattern, rules[pattern], source)
        assert result.startswith("group_operator = fields.Selection"), step
        assert 'fields.Float(aggregator="sum")' in result and 'aggregator = "avg",' in result
        assert 'self.group_operator == "sum": rec.group_operator = "avg"' in result


def test_117_blank_acl_rows_are_dropped_before_the_official_converter(tmp_path):
    mod = tmp_path / "bi_sql_editor"
    (mod / "security").mkdir(parents=True)
    manifest = mod / "__manifest__.py"
    manifest.write_text(repr({"name": "x", "data": ["security/ir.model.access.csv"]}), encoding="utf-8")
    acl = mod / "security" / "ir.model.access.csv"
    acl.write_text(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "access_x,access_x,model_x,base.group_user,1,1,1,1\n,,,,,,,\n",
        encoding="utf-8",
    )
    kept = _sanitize_acl_files([acl], mod, "bi_sql_editor", manifest, LOGGER)
    assert kept == [acl] and ",,,," not in acl.read_text(encoding="utf-8")


def test_118_names_in_a_data_list_and_base_model_hooks(tmp_path):
    addon(tmp_path, "base", code="class B(Model):\n    _name = 'base'\n")
    mod = addon(tmp_path, "auditlog", ["base"], """FIELDS_BLACKLIST = ["id", "write_date", "__last_update"]
class Rule(Model):
    _name = 'auditlog.rule'
    def _register_hook(self):
        super()._register_hook()
    def bad(self):
        return self.read(["__last_update"])
""")
    index = models.ModelIndex.build([tmp_path])
    found = messages(mod, index)
    assert len([m for m in found if "__last_update was removed" in m]) == 1  # the read() only
    assert not [m for m in found if "_register_hook() calls super()" in m]


def test_118_table_query_property_becomes_table_sql():
    source = (
        "from odoo import fields, models\n\n\nclass View(models.Model):\n    _name = 'x'\n    _auto = False\n\n"
        "    @property\n    def _table_query(self):\n        return f\"SELECT {self._select()}\"\n"
    )
    new, count = _convert(source)
    assert count == 1
    compile(new, "x.py", "exec")
    assert "from odoo.tools import SQL\n" in new and "def _table_sql(self):" in new
    assert 'return SQL("(%s)", query) if isinstance(query, SQL) else SQL(f"({query})")' in new
    assert _convert(new) == (new, 0)


def test_120_nested_order_line_keys_take_the_comodel(tmp_path):
    addon(tmp_path, "sale", code="""class SO(Model):
    _name = 'sale.order'
    order_line = fields.One2many('sale.order.line', 'order_id')
    partner_id = fields.Many2one('res.partner')
class SOL(Model):
    _name = 'sale.order.line'
    product_uom_id = fields.Many2one('uom.uom')
    product_id = fields.Many2one('product.product')
    product_uom_qty = fields.Float()
class POL(Model):
    _name = 'purchase.order.line'
    uom_id = fields.Many2one('uom.uom')
    product_id = fields.Many2one('product.product')
    product_uom_qty = fields.Float()
    name = fields.Char()
""")
    mod = addon(tmp_path, "delivery_price_rule_untaxed", ["sale"], """class T(TransactionCase):
    def test(self):
        self.env['sale.order'].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": self.product.id,
                "product_uom_qty": 1,
                "name": "PC",
                "product_uom": self.product_uom_unit.id,
            })],
        })
""")
    index = models.ModelIndex.build([tmp_path])
    # 18 -> 19 then 19 -> 20 (purchase.order.line product_uom_id -> uom_id:
    # the guess must not take the sale order line for a purchase one)
    for renames in ({("sale.order.line", "product_uom"): "product_uom_id"},
                    {("purchase.order.line", "product_uom_id"): "uom_id"}):
        python_checks.apply_field_renames(mod, index, renames)
    text = (mod / "models.py").read_text(encoding="utf-8")
    assert '"product_uom_id": self.product_uom_unit.id' in text and '"uom_id"' not in text



def test_override_gets_a_parameter_added_by_the_target(tmp_path):
    """delivery_price_rule_untaxed: 20.0 added wv=0.0 to
    delivery.carrier._get_price_from_picking / _get_price_dict."""
    addon(tmp_path, "delivery", code="""class Carrier(Model):
    _name = 'delivery.carrier'
    def _get_price_from_picking(self, total, weight, volume, quantity, wv=0.0):
        return 0.0
""")
    mod = addon(tmp_path, "delivery_price_rule_untaxed", ["delivery"], """class Carrier(Model):
    _inherit = 'delivery.carrier'
    def _get_price_from_picking(self, total, weight, volume, quantity):
        price_dict = {"wv": volume * weight}
        if not price_dict:
            return super()._get_price_from_picking(total, weight, volume, quantity)
        return 1.0
""")
    (mod / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    index = models.ModelIndex.build([tmp_path])
    changes = python_checks.apply_override_signature_migrations(mod, index)
    text = (mod / "models.py").read_text(encoding="utf-8")
    assert changes
    assert "def _get_price_from_picking(self, total, weight, volume, quantity, wv=0.0):" in text
    assert "super()._get_price_from_picking(total=total, weight=weight, volume=volume, quantity=quantity, wv=wv)" in text
    assert not [m for m in messages(mod, index) if "_get_price_from_picking" in m]
