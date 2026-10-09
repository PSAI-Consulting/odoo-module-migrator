"""Generic reproductions of migration failures observed on real addons."""

import ast
import logging

from odoo_module_migrate import quality, tools
from odoo_module_migrate.analysis import models, python_checks, views
from odoo_module_migrate.base_migration_script import BaseMigrationScript
from odoo_module_migrate.migration import Migration
from odoo_module_migrate.migration_scripts.migrate_180_190 import upgrade_sql_constraints
from odoo_module_migrate.migration_scripts.python_scripts.migrate_180_190.compatibility import (
    migrate_compatibility,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_180_190.sql_constraint_messages import (
    _unwrap_translated_constraint_messages,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_190_200.view_anchors import (
    migrate_view_anchors,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_190_200.view_expressions import (
    migrate_view_expressions,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_190_200.bank_account_fields import (
    migrate_bank_account_fields,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_190_200.line_descriptions import (
    check_line_descriptions,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_190_200.toggle_active import (
    _migrate_toggle_active_buttons,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_170_180.invisible_fields import (
    check_invisible_fields,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_170_180.product_storable import (
    migrate_product_storable,
)
from odoo_module_migrate.migration_scripts.migrate_170_180 import (
    replace_tree_with_list_in_views,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_170_180.env_translation import (
    migrate_env_translation,
)
from odoo_module_migrate.report import Entry, ModuleReport, ReportCollector


def addon(root, name, depends=(), code="", xml="", data=None):
    path = root / name
    path.mkdir(parents=True)
    (path / "__manifest__.py").write_text(
        repr(dict(name=name, depends=list(depends), data=data or ["view.xml"])),
        encoding="utf-8",
    )
    (path / "models.py").write_text(code, encoding="utf-8")
    (path / "view.xml").write_text("<odoo>" + xml + "</odoo>", encoding="utf-8")
    return path


def view(name, arch, parent=None):
    inherit = f'<field name="inherit_id" ref="{parent}"/>' if parent else ""
    return f'<record id="{name}" model="ir.ui.view">{inherit}<field name="arch" type="xml">{arch}</field></record>'


def test_dependency_reads_writes_relations_and_cycles(tmp_path):
    addon(tmp_path, "base", code="class P(Model):\n    _name = 'res.partner'\n")
    addon(
        tmp_path,
        "provider",
        ["consumer"],
        "class P(Model):\n    _inherit = 'res.partner'\n    custom_code = fields.Char()\nclass C(Model):\n    _name = 'custom.category'\n",
    )
    mod = addon(
        tmp_path,
        "consumer",
        ["base"],
        """class P(Model):
    _inherit = 'res.partner'
    partner_id = fields.Many2one('res.partner')
    def run(self):
        for record in self:
            record.partner_id.custom_code = 'x'
        self.env['res.partner'].write({'custom_code': 'y'})
        self.env['custom.category'].search([])
        other = self.env['res.partner'].browse(1)
        return other.custom_code
""",
    )
    index = models.ModelIndex.build([tmp_path, tmp_path])
    issues = list(python_checks.check_module(mod, index))
    assert len(issues) == 4, issues
    assert all(
        "circular dependency" in message and "provider" in message
        for _, _, _, message in issues
    )
    assert all(level == "error" for _, _, level, _ in issues)
    # A missing dependency should lower certainty, not abandon the analysis.
    index.depends["consumer"].append("unavailable")
    assert all(
        level == "warning" for _, _, level, _ in python_checks.check_module(mod, index)
    )


def test_callbacks_inherited_methods_override_and_precision(tmp_path):
    addon(
        tmp_path,
        "base",
        code="""class P(Model):
    _name = 'res.partner'
    def _compute_name(self): pass
    def _search_qty(self, operator, value): pass
""",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["base"],
        """class P(Model):
    _inherit = 'res.partner'
    name = fields.Char(compute='_compute_name')
    qty = fields.Float(search='_search_missing', digits='Missing precision')
    def _search_qty(self, operator, value):
        return []
""",
    )
    issues = list(
        python_checks.check_module(
            mod, models.ModelIndex.build([tmp_path]), precision_names={"Product Unit"}
        )
    )
    messages = [i[-1] for i in issues]
    assert len(messages) == 3, messages
    assert any("_search_missing" in m for m in messages)
    assert any("accidental override" in m for m in messages)
    assert any("decimal precision" in m for m in messages)
    assert not any("_compute_name" in m for m in messages)


def test_relational_alias_rename_and_purchase_api_diagnostics(tmp_path, caplog):
    addon(tmp_path, "base", code="class Base(Model):\n    _name = 'base'\n")
    addon(
        tmp_path,
        "purchase",
        ["base"],
        """class Order(Model):
    _name = 'purchase.order'
    order_line = fields.One2many('purchase.order.line', 'order_id')
class Line(Model):
    _name = 'purchase.order.line'
    order_id = fields.Many2one('purchase.order')
    uom_id = fields.Many2one('uom.uom')
    name = fields.Text()
    product_id = fields.Many2one('product.product')
class Product(Model):
    _name = 'product.product'
    display_name = fields.Char()
class Uom(Model):
    _name = 'uom.uom'
""",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["purchase"],
        """class Order(Model):
    _inherit = 'purchase.order'
    def confirm(self):
        for order in self:
            for line in order.order_line:
                seller = line.product_id._select_seller(uom_id=line.product_uom)
                label = line.name

class Line(Model):
    _inherit = 'purchase.order.line'
    def unchanged(self):
        draft_lines = self.filtered(lambda rec: rec.order_id)
        return all(
            rec.product_uom == rec._origin.product_uom for rec in draft_lines
        )
""",
        '<span t-esc="order_line.name"/>',
    )
    index = models.ModelIndex.build([tmp_path])

    changed = python_checks.apply_field_renames(
        mod, index, {("purchase.order.line", "product_uom"): "uom_id"}
    )

    assert len(changed) == 3
    assert "uom_id=line.uom_id" in (mod / "models.py").read_text()
    assert "rec.uom_id == rec._origin.uom_id" in (mod / "models.py").read_text()
    messages = [
        message
        for *_prefix, message in python_checks.check_module(mod, index, 20)
    ]
    assert any("returns a dict" in message for message in messages)
    assert any("without quantity" in message for message in messages)
    assert any("no longer includes the product name" in message for message in messages)
    caplog.set_level(logging.WARNING)
    check_line_descriptions(
        module_path=mod, tools=tools, logger=logging.getLogger("test")
    )
    assert "line .name no longer includes" in caplog.text

    corrected = (mod / "models.py").read_text().replace(
        "seller = line.product_id._select_seller(uom_id=line.uom_id)",
        "seller_info = line.product_id._select_seller(uom_id=line.uom_id)\n"
        "                seller = seller_info.get('supplierinfo', self.env['product.supplierinfo'])",
    )
    (mod / "models.py").write_text(corrected)
    corrected_messages = [
        message
        for *_prefix, message in python_checks.check_module(mod, index, 20)
    ]
    assert not any("returns a dict" in message for message in corrected_messages)
    assert any("without quantity" in message for message in corrected_messages)


def test_magic_fields_and_translation_in_implicit_scopes(tmp_path):
    addon(
        tmp_path,
        "base",
        code="""class Product(Model):
    _name = 'product.product'
    name = fields.Char()
""",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["base"],
        """from odoo import _, models
class Product(models.Model):
    _inherit = 'product.product'
    def labels(self, lines):
        regular = _('Regular')
        generated = ', '.join(_('Line %s', line) for line in lines)
        listed = [_('List %s', line) for line in lines]
        delayed = lambda value: _('Lambda %s', value)
        return self.id, self.display_name, self.create_date, regular, generated, listed, delayed
""",
    )
    index = models.ModelIndex.build([tmp_path])
    assert models.MAGIC_FIELDS <= index.fields["product.product"]
    assert not [
        message
        for _path, _line, _level, message in python_checks.check_module(mod, index)
        if "does not exist" in message
    ]

    migrate_env_translation(module_path=mod, tools=tools, logger=logging.getLogger("test"))

    result = (mod / "models.py").read_text()
    assert "regular = _('Regular')" in result
    assert result.count("self.env._") == 3
    assert "self.env._('Line %s', line)" in result
    assert "self.env._('List %s', line)" in result
    assert "self.env._('Lambda %s', value)" in result


def test_unicode_semantics_and_raw_strings():
    text = r"""a = "d\u00e9j\u00e0"
b = r"\u00e9"
c = "\\u00e9"
d = "\u0022"
e = b"\u00e9"
f = "\ud800"
# \u00e9
"""
    new = quality.readable_strings(text)
    assert '"déjà"' in new
    assert ast.dump(ast.parse(text)) == ast.dump(ast.parse(new))
    assert quality.readable_strings(new) == new
    assert "# \\u00e9" in new


def test_quality_and_manifest_access_order(tmp_path, caplog):
    mod = addon(
        tmp_path,
        "custom",
        code="\n\nclass P(Model):\n    _name = 'x.model'\n    def _compute_x(self):\n        self.write({'x': 1})\n        return _(f'Hello {self.id}')\n",
        data=["view.xml", "security/ir.access.csv"],
    )
    (mod / "l10n").mkdir()
    (mod / "l10n/fr.po").write_text("", encoding="utf-8")
    with caplog.at_level(logging.INFO, logger="odoo_module_migrate"):
        quality.finish_module(
            mod, original_data=["security/ir.model.access.csv", "view.xml"]
        )
    manifest = ast.literal_eval((mod / "__manifest__.py").read_text())
    assert manifest["data"] == ["security/ir.access.csv", "view.xml"]
    assert manifest["license"] == "LGPL-3"
    assert not (mod / "models.py").read_text().startswith("\n")
    for fragment in ("F821", "write()", "outside i18n"):
        assert fragment in caplog.text
    migrated = (mod / "models.py").read_text(encoding="utf-8")
    assert "_description = 'X Model'" in migrated
    assert "_('Hello %(id)s', id=self.id)" in migrated
    assert "INT001" not in caplog.text
    before = tools.hash_tree(mod)
    quality.finish_module(mod)
    assert tools.hash_tree(mod) == before


def test_oca_cosmetics_are_preserved(tmp_path):
    mod = addon(
        tmp_path,
        "oca",
        code='# Copyright OCA Contributors\n# License AGPL-3.0 or later\n\nname = "caf\\u00e9"\n',
    )
    manifest = mod / "__manifest__.py"
    manifest.write_text("# Copyright OCA Contributors\n" + manifest.read_text())
    before = tools.hash_tree(mod)
    quality.finish_module(mod, cosmetic=False)
    assert tools.hash_tree(mod) == before


def test_19_rewrites_are_scoped_and_idempotent(tmp_path, caplog):
    mod = addon(
        tmp_path,
        "custom",
        code="""# self._context
LABEL = "Product Unit of Measure self._context"
class P(Model):
    _inherit = 'res.partner'
    qty = fields.Float(digits = 'Product Unit of Measure')
    def run(self):
        self.env.ref('uom.uom_categ_length')
        self.env['decimal.precision'].precision_get('Product Unit of Measure')
        dp.get_precision("Product Unit of Measure")
        return self._context, self._cr, self._uid
""",
        xml="""<record id="uom_precision" model="decimal.precision">
<field name="name">Product Unit of Measure</field><field name="digits">5</field>
</record><record id="other" model="x"><field name="name">Product Unit of Measure</field></record>""",
    )
    args = dict(
        module_path=mod, tools=tools, logger=logging.getLogger("odoo_module_migrate")
    )
    migrate_compatibility(**args)
    text = (mod / "models.py").read_text()
    assert "digits = 'Product Unit'" in text
    assert "precision_get('Product Unit')" in text
    assert 'get_precision("Product Unit")' in text
    assert "return self.env.context, self.env.cr, self.env.uid" in text
    assert (
        "# self._context" in text and '"Product Unit of Measure self._context"' in text
    )
    assert "categories removed" in caplog.text
    xml = (mod / "view.xml").read_text()
    assert '<field name="name">Product Unit</field>' in xml
    assert '<record id="other"' in xml and "Product Unit of Measure" in xml
    migrate_compatibility(**args)
    assert (mod / "models.py").read_text() == text


def test_exact_xpath_and_targeted_repair(tmp_path):
    addon(tmp_path, "base")
    addon(
        tmp_path,
        "sale",
        ["base"],
        xml=view(
            "view_order_form",
            '<form><field name="order_line"><list><column name="price_unit"><field name="price_unit"/></column></list></field></form>',
        ),
    )
    expression = "//form/field[@name='order_line']/list[1]/field[@name='price_unit']"
    mod = addon(
        tmp_path,
        "custom",
        ["sale"],
        xml=view(
            "custom_form",
            f'<xpath expr="{expression}" position="before"><field name="x"/></xpath>',
            "sale.view_order_form",
        ),
    )
    index = views.ViewIndex.build([tmp_path])
    issues = list(views.check_module(mod, index, {"base", "sale"}))
    assert len(issues) == 1 and "Exact selector" in issues[0][-1]
    args = dict(
        module_path=mod, tools=tools, logger=logging.getLogger("odoo_module_migrate")
    )
    migrate_view_anchors(**args)
    assert not list(
        views.check_module(mod, views.ViewIndex.build([tmp_path]), {"base", "sale"})
    )
    text = (mod / "view.xml").read_text()
    migrate_view_anchors(**args)
    assert (mod / "view.xml").read_text() == text


def test_product_header_anchor_moves_before_sheet(tmp_path):
    mod = addon(
        tmp_path,
        "custom",
        xml=view(
            "form",
            '<header position="before"><div class="alert">Review</div></header>',
            "product.product_normal_form_view",
        ),
    )
    args = dict(
        module_path=mod, tools=tools, logger=logging.getLogger("odoo_module_migrate")
    )
    migrate_view_anchors(**args)
    text = (mod / "view.xml").read_text()
    assert '<sheet position="before"><div class="alert">Review</div></sheet>' in text
    migrate_view_anchors(**args)
    assert (mod / "view.xml").read_text() == text


def test_bank_account_field_in_python_commands_and_qweb(tmp_path):
    mod = addon(
        tmp_path,
        "custom",
        code="""class Importer(Model):
    _name = "x.importer"
    def run(self, partner, values):
        account = self.env["res.partner.bank"].search([("acc_number", "=", values.get("acc_number"))])
        partner.write({"bank_ids": [(0, 0, {"acc_number": values.get("acc_number")})]})
        return values.get("acc_number"), account, partner_bank.bank_id.name, partner_bank.bank_id.bic
""",
        xml="""<template id="report">
<span t-field="partner_bank.acc_number"/>
<span t-esc="partner_bank.acc_number[:4] + supplier_bank.acc_number"/>
<t t-if="partner_bank.bank_id" t-out="partner_bank.bank_id.name + partner_bank.bank_id.bic"/>
</template>""",
    )
    args = dict(
        module_path=mod, tools=tools, logger=logging.getLogger("odoo_module_migrate")
    )
    migrate_bank_account_fields(**args)
    python = (mod / "models.py").read_text()
    xml = (mod / "view.xml").read_text()
    assert python.count('values.get("acc_number")') == 3
    assert '("account_number", "=",' in python
    assert '{"account_number": values.get' in python
    assert xml.count(".account_number") == 3
    assert ".acc_number" not in xml
    assert "partner_bank.bank_name" in python
    assert "partner_bank.bank_bic" in python
    assert 't-if="partner_bank.bank_name"' in xml
    assert "partner_bank.bank_name + partner_bank.bank_bic" in xml
    assert ".bank_id" not in python + xml
    before = tools.hash_tree(mod)
    migrate_bank_account_fields(**args)
    assert tools.hash_tree(mod) == before


def test_ambiguous_acc_number_is_reported_not_rewritten(tmp_path, caplog):
    mod = addon(
        tmp_path,
        "custom",
        code="def value(record):\n    return record.acc_number\n",
        xml='<span t-field="record.acc_number"/>',
    )
    with caplog.at_level(logging.ERROR, logger="odoo_module_migrate"):
        migrate_bank_account_fields(
            module_path=mod,
            tools=tools,
            logger=logging.getLogger("odoo_module_migrate"),
        )
    assert "record.acc_number" in (mod / "models.py").read_text()
    assert 't-field="record.acc_number"' in (mod / "view.xml").read_text()
    assert "Ambiguous .acc_number access" in caplog.text
    assert "Ambiguous .acc_number in QWeb" in caplog.text


def test_journal_bank_account_number_is_renamed_with_resolved_model(tmp_path):
    addon(
        tmp_path,
        "account",
        code="""class Journal(Model):
    _name = "account.journal"
    bank_account_number = fields.Char()
""",
    )
    custom = addon(
        tmp_path,
        "custom",
        ["account"],
        code="""class Journal(Model):
    _inherit = "account.journal"
    def number(self):
        return self.bank_acc_number
""",
    )
    index = models.ModelIndex.build([tmp_path])

    changes = python_checks.apply_field_renames(
        custom,
        index,
        {("account.journal", "bank_acc_number"): "bank_account_number"},
    )

    assert len(changes) == 1
    assert "self.bank_account_number" in (custom / "models.py").read_text(
        encoding="utf-8"
    )


def test_unknown_dependency_and_risk(tmp_path):
    addon(tmp_path, "base", xml=view("form", "<form><group/></form>"))
    mod = addon(
        tmp_path,
        "custom",
        ["base", "missing"],
        xml=view(
            "form",
            '<xpath expr="//group[@expand=\'0\']" position="inside"/>',
            "base.form",
        ),
    )
    issues = list(views.check_module(mod, views.ViewIndex.build([tmp_path]), {"base"}))
    assert issues and "incomplete dependencies" in issues[0][-1]
    report = ModuleReport(
        "custom", mod, [Entry("WARNING", "[incomplete] missing dependency")]
    )
    assert report.risk == "inconnu"


def test_cache_invalidates_and_context_is_deduplicated(tmp_path):
    mod = addon(
        tmp_path,
        "base",
        code="class P(Model):\n    _name = 'res.partner'\n    a = fields.Char()\n",
    )
    assert list(views._module_dirs([tmp_path, tmp_path])) == [mod]
    assert "a" in models.ModelIndex.build([tmp_path]).fields["res.partner"]
    (mod / "models.py").write_text(
        "class P(Model):\n    _name = 'res.partner'\n    b = fields.Char()\n"
    )
    index = models.ModelIndex.build([tmp_path])
    assert "b" in index.fields["res.partner"] and "a" not in index.fields["res.partner"]


def test_invisible_notice_only_for_used_fields(tmp_path, caplog):
    mod = addon(
        tmp_path,
        "custom",
        xml=view(
            "form",
            '<form><field name="used" invisible="1"/><field name="unused" invisible="1"/><field name="name" readonly="used"/></form>',
        ),
    )
    check_invisible_fields(
        module_path=mod, tools=tools, logger=logging.getLogger("odoo_module_migrate")
    )
    assert "Invisible field used" in caplog.text
    assert "Invisible field unused" not in caplog.text


def test_small_migration_end_to_end(tmp_path):
    mod = addon(
        tmp_path,
        "custom",
        ["base"],
        "from odoo import fields, models\nclass P(models.Model):\n    _inherit = 'res.partner'\n    qty = fields.Float(digits='Product Unit of Measure')\n",
    )
    migration = Migration(
        tmp_path, "18.0", "19.0", ["custom"], commit_enabled=False, pre_commit=False
    )
    migration.run()
    assert "digits='Product Unit'" in (mod / "models.py").read_text()
    assert (mod / "MIGRATION_REPORT.md").exists()


def test_formatter_only_changed_non_oca_files(tmp_path, monkeypatch):
    from types import SimpleNamespace

    mod = addon(tmp_path, "custom", code="import os\n")
    (mod / "__init__.py").write_text("from . import models\n")
    (mod / "untouched.py").write_text("import sys\n")
    (tmp_path / ".ruff.toml").write_text("line-length = 99\n")
    migration = Migration(
        tmp_path,
        "18.0",
        "19.0",
        ["custom"],
        commit_enabled=False,
        pre_commit=False,
        format_code=True,
    )
    item = migration._module_migrations[0]
    item._hashes_before = tools.hash_tree(mod)
    (mod / "models.py").write_text("import os\nx=1\n")
    (mod / "__init__.py").write_text("from . import models\n\n")
    commands = []
    monkeypatch.setattr("shutil.which", lambda name: "ruff")
    monkeypatch.setattr(
        "subprocess.run",
        lambda command, **kw: commands.append(command) or SimpleNamespace(returncode=0),
    )
    migration._format_changed_files()
    assert len(commands) == 1
    assert all("untouched.py" not in " ".join(command) for command in commands)
    assert all(str(tmp_path / ".ruff.toml") in command for command in commands)
    assert not any(
        "check" in command and command[-1].endswith("__init__.py")
        for command in commands
    )


def test_manifest_template_preserves_customer_values_and_load_order():
    from odoo_module_migrate.manifest import format_manifest

    original = """# Copyright Example
{
    # business ordering matters
    'data': ['data/first.xml', 'security/ir.access.csv', 'views/form.xml'],
    'author': 'Another Customer',
    'name': 'Café',
    'version': '20.0.1.2.3',
    'description': '',
    'installable': True,
    'auto_install': ['sale'],
    'application': False,
    'custom_key': {'a': True},
}
"""
    result = format_manifest(original, default_website="https://example.test")
    data = ast.literal_eval(result)
    assert data["author"] == "Another Customer"
    assert data["data"] == ast.literal_eval(original)["data"]
    assert data["auto_install"] == ["sale"]
    assert data["license"] == "LGPL-3"
    assert data["website"] == "https://example.test"
    assert "installable" not in data and "description" not in data
    assert "# Copyright Example" in result and "# business ordering matters" in result
    assert format_manifest(result) == result


def test_manifest_list_rewrite_handles_first_item_on_opening_line():
    from odoo_module_migrate.manifest import format_manifest, rewrite_list

    intermediate = """{
    'name': 'x',
    'data': ['security/ir.access.csv',
        'views/first.xml',
        'views/last.xml',
    ],
}
"""
    rewritten = rewrite_list(
        intermediate,
        "data",
        ["views/first.xml", "views/last.xml", "security/ir.access.csv"],
    )
    assert ast.literal_eval(rewritten)["data"][-1] == "security/ir.access.csv"
    assert ast.literal_eval(format_manifest(rewritten))["data"][-1] == (
        "security/ir.access.csv"
    )


def test_html_field_append_and_malformed_break_are_reported(tmp_path):
    addon(tmp_path, "base", code="class Base(Model):\n    _name = 'base'\n")
    mod = addon(
        tmp_path,
        "custom",
        ["base"],
        """class Wizard(TransientModel):
    _name = 'custom.wizard'
    message_html = fields.Html()
    message_text = fields.Char()

    def compute_message(self):
        for wizard in self:
            wizard.message_html += '</br> - %s' % wizard.display_name
            wizard.message_text += 'safe plain text'
""",
    )
    index = models.ModelIndex.build([tmp_path])
    messages = [issue[-1] for issue in python_checks.check_module(mod, index)]
    assert len([message for message in messages if "extended with +=" in message]) == 1
    assert len([message for message in messages if "Malformed HTML" in message]) == 1


def test_manifest_scaffold_comments_removed_business_comments_preserved():
    from odoo_module_migrate.manifest import format_manifest

    original = """# -*- coding: utf-8 -*-
{
    'name': 'Composition',
    # Categories can be used to filter modules in modules listing
    # for the full list
    'category': 'base',
    # Explanation specific to this module
    'depends': ['base', 'product'],  # Keep this inline note
    # always loaded
    'data': ['views/product.xml'],
}
"""
    result = format_manifest(original)
    assert "Categories can be used" not in result
    assert "for the full list" not in result
    assert "always loaded" not in result
    assert "# Explanation specific to this module" in result
    assert "# Keep this inline note" in result
    assert result.index("# Explanation specific") < result.index('"depends"')
    assert result.index("# Keep this inline") < result.index('"depends"')
    assert format_manifest(result) == result


def test_manifest_multiline_description_and_empty_optional_keys():
    from odoo_module_migrate.manifest import format_manifest

    original = '''{
    "name": "Validation",
    "summary": "",
    "description": """
        Validate invoices automatically.
        Keep failures in draft.
    """,
    "external_dependencies": {},
    "demo": [],
    "assets": {},
    "depends": ["account"],
}
'''
    result = format_manifest(original)
    data = ast.literal_eval(result)
    assert "summary" not in data
    assert "external_dependencies" not in data
    assert "demo" not in data
    assert "assets" not in data
    assert '"description": """\n' in result
    assert "        Validate invoices automatically." in result
    assert format_manifest(result) == result


def test_scheduled_action_method_must_come_from_dependencies(tmp_path):
    addon(
        tmp_path,
        "account",
        code="class Move(Model):\n    _name = 'account.move'\n",
    )
    addon(
        tmp_path,
        "account_invoice_extract",
        ["account"],
        code="class Move(Model):\n    _inherit = 'account.move'\n    def _cron_validate(self): pass\n",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["account"],
        code="class Move(Model):\n    _inherit = 'account.move'\n    def _cron_validate_invoices(self): pass\n",
        xml="""<record id="cron" model="ir.cron">
<field name="model_id" ref="account.model_account_move"/>
<field name="code">model._cron_validate()</field>
</record>""",
    )
    index = models.ModelIndex.build([tmp_path])
    issues = list(python_checks.check_module(mod, index))
    action_issues = [
        issue for issue in issues if "Scheduled/server action" in issue[-1]
    ]
    assert len(action_issues) == 1
    assert action_issues[0][2] == "warning"
    assert "account_invoice_extract" in action_issues[0][-1]
    assert "outside this module's dependencies" in action_issues[0][-1]

    (mod / "view.xml").write_text(
        (mod / "view.xml")
        .read_text()
        .replace("model._cron_validate()", "model._cron_validate_invoices()")
    )
    assert not [
        issue
        for issue in python_checks.check_module(mod, index)
        if "Scheduled/server action" in issue[-1]
    ]


def test_super_call_to_removed_parent_method_is_reported(tmp_path):
    addon(tmp_path, "base", code="class Base(Model):\n    _name = 'base'\n")
    addon(
        tmp_path,
        "crm",
        ["base"],
        """class Lead(Model):
    _name = 'crm.lead'
    def _prepare_customer_values(self, partner_name, parent_id=False): pass
""",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["crm"],
        """class Lead(Model):
    _inherit = 'crm.lead'
    def _create_lead_partner_data(self, name, is_company, parent_id=False):
        return super()._create_lead_partner_data(name, is_company, parent_id)
""",
    )

    index = models.ModelIndex.build([tmp_path])
    index.renamed_methods[("crm.lead", "_create_lead_partner_data")] = (
        "_prepare_customer_values",
        "odoo d8b6b35cb3c",
    )
    messages = [
        message
        for _path, _line, _level, message in python_checks.check_module(
            mod, index
        )
    ]

    assert len(messages) == 1
    assert "no parent method with that name exists" in messages[0]
    assert "_prepare_customer_values" in messages[0]


def test_compute_override_reports_changed_target_dependencies(tmp_path):
    addon(tmp_path, "base", code="class Base(Model):\n    _name = 'base'\n")
    addon(
        tmp_path,
        "purchase",
        ["base"],
        """class Line(Model):
    _name = 'purchase.order.line'
    @api.depends('product_qty', 'uom_id', 'company_id', 'order_id.partner_id')
    def _compute_price_unit_and_date_planned_and_name(self):
        pass
""",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["purchase"],
        """class Line(Model):
    _inherit = 'purchase.order.line'
    @api.depends('product_qty', 'uom_id', 'company_id')
    def _compute_price_unit_and_date_planned_and_name(self):
        return
""",
    )
    index = models.ModelIndex.build([tmp_path])
    messages = [issue[-1] for issue in python_checks.check_module(mod, index)]
    changed = [message for message in messages if "different @api.depends" in message]
    assert len(changed) == 1
    assert "missing order_id.partner_id" in changed[0]


def test_iterated_super_result_keeps_record_model_for_field_renames(tmp_path):
    addon(tmp_path, "base", code="class Base(Model):\n    _name = 'base'\n")
    addon(
        tmp_path,
        "account",
        ["base"],
        """class Move(Model):
    _name = 'account.move'
    invoice_line_ids = fields.One2many('account.move.line', 'move_id')
class MoveLine(Model):
    _name = 'account.move.line'
    move_id = fields.Many2one('account.move')
    sale_line_ids = fields.Many2many('sale.order.line')
class SaleLine(Model):
    _name = 'sale.order.line'
    uom_id = fields.Many2one('uom.uom')
""",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["account"],
        """class Move(Model):
    _inherit = 'account.move'
    def _reverse_moves(self):
        result = super()._reverse_moves()
        for move in result:
            for invoice_line in move.invoice_line_ids:
                for sale_line in invoice_line.sale_line_ids:
                    first = sale_line.product_uom
                    second = sale_line.product_uom
""",
    )
    index = models.ModelIndex.build([tmp_path])
    changed = python_checks.apply_field_renames(
        mod, index, {("sale.order.line", "product_uom"): "uom_id"}
    )
    assert len(changed) == 2
    assert "sale_line.product_uom" not in (mod / "models.py").read_text()


def test_replaced_standard_method_suggests_reachable_target_hooks(tmp_path):
    addon(tmp_path, "base", code="class Base(Model):\n    _name = 'base'\n")
    addon(
        tmp_path,
        "sale",
        ["base"],
        """class Line(Model):
    _name = 'sale.order.line'
    def _compute_qty_invoiced(self):
        values = self._prepare_qty_invoiced()
    def _prepare_qty_invoiced(self):
        return [line for line in self if self._affects_qty_invoiced(line)]
    def _affects_qty_invoiced(self, invoice_line):
        return True
""",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["sale"],
        """class Line(Model):
    _inherit = 'sale.order.line'
    def _compute_qty_invoiced(self):
        for line in self:
            line.qty_invoiced = 0
""",
    )
    index = models.ModelIndex.build([tmp_path])
    messages = [issue[-1] for issue in python_checks.check_module(mod, index)]
    hooks = [message for message in messages if "target extension hooks" in message]
    assert len(hooks) == 1
    assert "_prepare_qty_invoiced" in hooks[0]
    assert "_affects_qty_invoiced" in hooks[0]


def test_dynamic_document_records_and_base_default_get_are_checked(tmp_path):
    addon(tmp_path, "base", code="class Base(Model):\n    _name = 'base'\n")
    addon(
        tmp_path,
        "documents",
        ["base"],
        """class Document(Model):
    _name = 'documents.document'
    type = fields.Selection([])
""",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["documents"],
        """class StoredDocuments(Model):
    _name = 'stored.documents'
    document_ids = fields.Many2many('documents.document')

class OrdinaryModal(Model):
    _name = 'ordinary.modal'

class DocumentWizard(Model):
    _name = 'document.widgets'
    line_ids = fields.One2many('document.widgets.line', 'wizard_id')

    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        active = self.env[self.env.context.get('active_model')].browse(
            self.env.context.get('active_id')
        )
        if active.document_ids:
            active.document_ids = [(5, 0, 0)]
        for document in self:
            active.document_ids += document.file_id
        return values

class DocumentWizardLine(TransientModel):
    _name = 'document.widgets.line'
    wizard_id = fields.Many2one('document.widgets')
    file_id = fields.Many2one('documents.document')
    safe_file_id = fields.Many2one(
        'documents.document', domain=[('type', '!=', 'folder')]
    )
""",
        xml="""<record id="wizard_view" model="ir.ui.view">
<field name="model">document.widgets</field><field name="arch" type="xml">
<form><field name="line_ids"><list>
<field name="file_id"/><field name="safe_file_id"/>
</list></field></form>
</field></record>
<record id="wizard_action" model="ir.actions.act_window">
<field name="res_model">document.widgets</field>
<field name="view_mode">form</field><field name="target">new</field>
</record>
<record id="ordinary_modal_action" model="ir.actions.act_window">
<field name="res_model">ordinary.modal</field>
<field name="view_mode">form</field><field name="target">new</field>
</record>""",
    )

    index = models.ModelIndex.build([tmp_path])
    messages = [
        message
        for _path, _line, _level, message in python_checks.check_module(
            mod, index, target_version=20
        )
    ]

    assert not [message for message in messages if "default_get() calls super" in message]
    folder_messages = [message for message in messages if "folders are documents" in message]
    assert len(folder_messages) == 1
    assert folder_messages[0].startswith("file_id links")
    assert not [message for message in messages if message.startswith("document_ids links")]
    assert len([message for message in messages if "dynamic field access" in message]) == 1
    updates = [message for message in messages if "Dynamic-model x2many update" in message]
    assert len(updates) == 1
    assert "Command.set(ids)" in updates[0]
    wizard_messages = [message for message in messages if "looks like a wizard" in message]
    assert len(wizard_messages) == 1
    assert wizard_messages[0].startswith("document.widgets inherits")
    assert "models.TransientModel" in wizard_messages[0]


def test_product_view_detailed_type_values_are_migrated(tmp_path):
    xml = """<record id="form" model="ir.ui.view">
<field name="model">product.template</field>
<field name="arch" type="xml"><form>
<button invisible="detailed_type == 'service'"/>
<button invisible="detailed_type == &quot;consu&quot;"/>
<button invisible="detailed_type != 'consu'"/>
</form></field></record>"""
    mod = addon(tmp_path, "custom", xml=xml)
    migrate_product_storable(
        module_path=mod, tools=tools, logger=logging.getLogger("odoo_module_migrate")
    )
    text = (mod / "view.xml").read_text()
    assert "detailed_type" not in text
    assert "type == 'service'" in text
    assert "type == 'consu' and not is_storable" in text
    assert "(type != 'consu' or is_storable)" in text


def test_unused_import_cleanup_preserves_initializers_and_noqa(tmp_path):
    mod = addon(
        tmp_path,
        "custom",
        code='# License AGPL-3.0 or later\n\nfrom itertools import groupby\n\nfrom odoo import api, models\n\n\nclass Partner(models.Model):\n    _inherit = "res.partner"\n',
    )
    manifest = mod / "__manifest__.py"
    manifest.write_text("# Copyright Example\n# @author Someone\n\n" + manifest.read_text())
    (mod / "__init__.py").write_text("from . import models\n")
    (mod / "hook.py").write_text("import registration  # noqa: F401\n")
    migration = Migration(
        tmp_path,
        "19.0",
        "20.0",
        ["custom"],
        commit_enabled=False,
        pre_commit=False,
        clean_imports=True,
    )
    quality.finish_module(mod, cosmetic=True)
    migration._format_changed_files()
    source = (mod / "models.py").read_text()
    assert source.startswith("from odoo import models\n")
    assert "api" not in source and "groupby" not in source
    assert "Copyright" not in manifest.read_text() and "@author" not in manifest.read_text()
    assert (mod / "__init__.py").read_text() == "from . import models\n"
    assert "import registration" in (mod / "hook.py").read_text()


def test_import_only_initializers_have_no_blank_lines(tmp_path):
    mod = addon(tmp_path, "custom")
    models = mod / "models"
    models.mkdir()
    initializer = models / "__init__.py"
    initializer.write_text(
        "\nfrom . import partner\n\n\n# models grouped before\n\nfrom . import product\n\n",
        encoding="utf-8",
    )
    quality.finish_module(mod)
    assert initializer.read_text(encoding="utf-8") == (
        "from . import partner\n# models grouped before\nfrom . import product\n"
    )


def test_initializer_with_runtime_code_keeps_internal_spacing(tmp_path):
    mod = addon(tmp_path, "custom")
    initializer = mod / "__init__.py"
    initializer.write_text(
        "\nVALUE = '''first\n\nsecond'''\n\nregister(VALUE)\n",
        encoding="utf-8",
    )
    quality.finish_module(mod)
    assert "first\n\nsecond" in initializer.read_text(encoding="utf-8")


def test_transitive_merged_dependencies_are_resolved(tmp_path):
    addon(tmp_path, "custom", ["bridge"])
    migration = Migration(
        tmp_path, "19.0", "20.0", ["custom"], commit_enabled=False, pre_commit=False
    )
    index = views.ViewIndex()
    index.depends = {
        "custom": ["bridge"],
        "bridge": ["stock_picking_batch"],
        "stock": ["base"],
        "base": [],
    }
    migration._resolve_index_dependencies(index)
    assert not index.unknown_dependencies("custom")
    assert "stock" in index.closure("custom")


def test_accessible_dependency_files_not_iterated_by_official_scripts(tmp_path):
    from types import SimpleNamespace
    from odoo_module_migrate.upgrade_code import runner

    class Manager:
        def get_file(self, module, filename):
            return self._files[module]

    uc = SimpleNamespace(FileManager=Manager)
    runner.patch_file_manager(uc, set())
    manager = Manager()
    target = tmp_path / "custom"
    manager._target_roots = (target,)
    manager._modules = {"custom": target, "base": tmp_path / "base"}
    manager._files = {
        name: SimpleNamespace(path=path / "models.py", dirty=False)
        for name, path in manager._modules.items()
    }
    assert list(manager) == [manager._files["custom"]]
    assert manager.get_file("base", "models.py") is manager._files["base"]


def test_sql_style_apostrophes_are_repaired_and_other_joins_reported(tmp_path, caplog):
    mod = addon(tmp_path, "custom", code="""from odoo import models

class Input(models.AbstractModel):
    _name = "custom.input"
    _description = 'Interface for l''envoi'
    _help = "Glued""text"
    _spaced = 'kept' 'as is'
""")
    (mod / "__manifest__.py").write_text(
        "{'name': 'Custom', 'summary': 'Méthodes d''entrée', 'depends': ['base']}\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="odoo_module_migrate"):
        quality.finish_module(mod, manifest_layout=True)

    assert "Méthodes d'entrée" in (mod / "__manifest__.py").read_text(encoding="utf-8")
    code = (mod / "models.py").read_text(encoding="utf-8")
    assert ast.literal_eval(code.split("_description = ")[1].splitlines()[0]) == (
        "Interface for l'envoi"
    )
    assert "'kept' 'as is'" in code
    # Only the ambiguous double-quoted join is left as a diagnostic.
    warnings = [r.message for r in caplog.records if "Adjacent" in r.message]
    assert len(warnings) == 1 and "Glued" in warnings[0]


def test_access_rows_on_abstract_models_are_reported_in_both_csv_formats(tmp_path):
    mod = addon(tmp_path, "custom", code="""from odoo import models

class Input(models.AbstractModel):
    _name = "custom.input"
    _description = "Input"

class Concrete(models.Model):
    _name = "custom.concrete"
    _description = "Concrete"
""")
    security = mod / "security"
    security.mkdir()
    (security / "ir.access.csv").write_text(
        "id,name,model_id,group_id/id,operation,domain\n"
        "abstract,abstract,custom.input,base.group_user,read,\n"
        "concrete,concrete,custom.concrete,base.group_user,read,\n",
        encoding="utf-8",
    )
    index = models.ModelIndex.build([tmp_path])
    issues = list(models.check_abstract_access(mod, index))
    assert len(issues) == 1
    assert issues[0][1] == 2
    assert "custom.input" in issues[0][2]

    (security / "ir.access.csv").unlink()
    (security / "ir.model.access.csv").write_text(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "abstract,abstract,model_custom_input,base.group_user,1,0,0,0\n",
        encoding="utf-8",
    )
    issues = list(models.check_abstract_access(mod, index))
    assert len(issues) == 1
    assert "custom.input" in issues[0][2]


def test_odoo20_runtime_api_and_python_errors_are_reported(tmp_path):
    mod = addon(tmp_path, "custom", code="""import base64
from odoo import api, fields, models

class Thing(models.Model):
    _name = "custom.thing"
    _description = "Thing"
    image = fields.Image()
    result = fields.Char(compute="_compute_result")
    password = fields.Char()

    def _compute_result(self):
        self.password = False
        self.result = "ok"

    def create(self, vals):
        self.image = base64.b64encode(b"png")
        if not self.env.get("optional.model"):
            pass
        if isinstance(self.image, fields.Image):
            pass
        try:
            raise f"bad {vals}"
        except:
            pass
        self.env["ir.config_parameter"].get_param("key")
        self.env["ir.attachment"]._file_read("name")
        self.env.cr.execute("DELETE FROM mail_tracking_value")
        return super().create(vals)
""")
    index = models.ModelIndex.build([tmp_path])
    messages = [
        message
        for _path, _line, _level, message in python_checks.check_module(
            mod, index, target_version=20
        )
    ]
    expected = [
        "model_create_multi",
        "base64.b64encode",
        "env.get",
        "isinstance(record.value",
        "cannot raise a string",
        "Bare except",
        "get_param",
        "_file_read",
        "mail_tracking_value",
        "writes other field password",
    ]
    for fragment in expected:
        assert any(fragment in message for message in messages), fragment


def test_odoo20_view_expression_and_widget_rewrites_are_scoped_to_views(tmp_path):
    mod = addon(tmp_path, "custom", xml="""<record id="view" model="ir.ui.view">
<field name="model">custom.thing</field><field name="arch" type="xml"><form>
<field name="line_ids" context="{'default_parent_id': active_id}" widget="kanban"/>
<field name="path" widget="DynamicModelFieldSelectorChar" style="width:200%%"/>
</form></field></record>
<record id="action" model="ir.actions.act_window">
<field name="context">{'default_parent_id': active_id}</field></record>""")
    migrate_view_expressions(
        module_path=mod, tools=tools, logger=logging.getLogger("test")
    )
    text = (mod / "view.xml").read_text()
    assert "default_parent_id': id" in text
    assert 'mode="kanban"' in text and 'widget="kanban"' not in text
    assert 'widget="field_selector"' in text
    assert "width:200%" in text and "200%%" not in text
    assert "<field name=\"context\">{'default_parent_id': active_id}" in text


def test_circular_dependency_todos_are_grouped_by_method(tmp_path):
    mod = addon(tmp_path, "custom", code="""class Worker:
    def send(self):
        first = 1
        second = 2
""")
    collector = ReportCollector([("custom", mod)])
    for line, item in ((3, "Field worker.task_id"), (4, "Model edi.file")):
        record = logging.LogRecord(
            "test",
            logging.ERROR,
            "",
            0,
            f"{item}: circular dependency; move this code into provider "
            f"(field/model provider) or a bridge module. File {mod / 'models.py'}:{line}",
            (),
            None,
        )
        collector.emit(record)
    entries = collector.reports["custom"].entries
    assert len(entries) == 1
    assert entries[0].line == 2
    assert "Method send uses Field worker.task_id, Model edi.file" in entries[0].message


def test_known_view_widget_provider_must_be_a_dependency(tmp_path):
    addon(tmp_path, "base", data=[])
    addon(tmp_path, "account", ["base"], data=[])
    mod = addon(
        tmp_path,
        "custom",
        ["base"],
        xml="""<record id="view" model="ir.ui.view"><field name="model">x</field>
<field name="arch" type="xml"><form><field name="line_ids" widget="section_and_note_one2many"/></form></field></record>""",
    )
    index = views.ViewIndex.build([tmp_path])
    issues = list(views.check_module(mod, index, {"base", "account"}))
    assert any("widget 'section_and_note_one2many'" in message and "account" in message for _path, _line, message in issues)
    assert views.apply_known_widget_dependencies(mod, index) == ["account"]
    manifest = ast.literal_eval((mod / "__manifest__.py").read_text())
    assert manifest["depends"] == ["base", "account"]
    assert not [
        message
        for _path, _line, message in views.check_module(
            mod, index, {"base", "account"}
        )
        if "section_and_note_one2many" in message
    ]


def test_binaryvalue_operations_are_fixed_when_field_type_is_proven(tmp_path):
    mod = addon(tmp_path, "custom", code="""import base64
import io
from odoo import fields, models

class File(models.Model):
    _name = "custom.file"
    _description = "File"
    file = fields.Binary()
    encoding = fields.Char()

    def convert(self, raw):
        stream = io.BytesIO(base64.b64decode(self.file))
        self.file = base64.b64encode(raw)
        self.create({"file": base64.b64encode(raw)})
        payload = self.file.decode()
        ascii_payload = self.file.decode("ascii")
        decoded_text = self.file.decode(self.encoding)
        external_payload = base64.b64encode(raw).decode()
        return stream, payload, ascii_payload, decoded_text, external_payload

    def payload(self, item):
        return item.file.decode()

    def call_payload(self):
        return self.payload(item=self)
""")
    index = models.ModelIndex.build([tmp_path])
    changes = python_checks.apply_binaryvalue_migrations(mod, index)
    text = (mod / "models.py").read_text(encoding="utf-8")
    assert len(changes) == 6
    assert "io.BytesIO(self.file.content)" in text
    assert "self.file = BinaryBytes(raw)" in text
    assert 'self.create({"file": BinaryBytes(raw)})' in text
    assert text.count("self.file.to_base64()") == 2
    assert "return item.file.to_base64()" in text
    assert "self.file.decode(self.encoding)" in text
    assert "base64.b64encode(raw).decode()" in text
    assert text.count("from odoo.tools.binary import BinaryBytes") == 1
    messages = [
        message
        for _path, _line, _level, message in python_checks.check_module(
            mod, index, target_version=20
        )
    ]
    decode_messages = [message for message in messages if "BinaryValue" in message and "decode()" in message]
    assert len(decode_messages) == 1


def test_self_field_read_inside_record_loop_is_reported(tmp_path):
    mod = addon(tmp_path, "custom", code="""from odoo import fields, models

class Task(models.Model):
    _name = "custom.task"
    _description = "Task"
    delete_after = fields.Boolean()

    def process(self):
        for task in self:
            if self.delete_after:
                task.unlink()
            self.env["res.partner"]
""")
    index = models.ModelIndex.build([tmp_path])
    messages = [
        message
        for _path, _line, _level, message in python_checks.check_module(
            mod, index, target_version=20
        )
    ]
    matching = [message for message in messages if "for task in self" in message]
    assert len(matching) == 1
    assert "task.delete_after" in matching[0]


def test_runtime_view_cursor_and_singleton_name_get_are_migrated(tmp_path):
    mod = addon(tmp_path, "custom", code="""from odoo import fields, models

class Item(models.Model):
    _name = "custom.item"
    _description = "Item"
    view_id = fields.Many2one("ir.ui.view", "EDI Tree View")

    def build(self):
        self.env.cr.commit()
        self.env.cr.clear()
        self.env["ir.ui.view"].create({"type": "tree", "arch": "<tree/>"})
        self.env["ir.actions.act_window"].create({"view_mode": "tree,form"})
        for item in self:
            pair = item.name_get()[0]
        self.env.cr.reset()
        return pair
""")
    index = models.ModelIndex.build([tmp_path])
    changes = python_checks.apply_runtime_api_migrations(mod, index, 20)
    text = (mod / "models.py").read_text(encoding="utf-8")
    assert len(changes) == 4
    assert "self.env.transaction.clear()" in text
    assert '"type": \'list\'' in text
    assert '"view_mode": \'list,form\'' in text
    assert "(item.id, item.display_name)" in text
    assert "EDI Tree View" in text
    assert "get_external_id" in models.BASE_METHODS
    messages = [
        message
        for _path, _line, _level, message in python_checks.check_module(
            mod, index, target_version=20
        )
    ]
    assert any("Cursor.clear()/reset() was removed" in message for message in messages)


def test_odoo20_typed_config_parameters_and_loop_fields_are_migrated(tmp_path):
    mod = addon(tmp_path, "custom", code="""from odoo import fields, models

class Task(models.Model):
    _name = "custom.task"
    _description = "Task"
    enabled = fields.Boolean()

    def run(self):
        config = self.env["ir.config_parameter"].sudo()
        count = int(config.get_param("count") or 0)
        ratio = float(config.get_param("ratio") or 1.5)
        title = config.get_param("title") or "Default"
        enabled = config.get_param("enabled") == "True"
        raw = config.get_param("raw")
        config.set_param("attempts", 3)
        config.set_param("dynamic", self.enabled)
        legacy_false = config.get_param("legacy_false") == "False"
        truthy_text = bool(config.get_param("truthy_text"))
        explicit_default = config.get_param("explicit", False)
        for task in self:
            if self.enabled:
                task.enabled = False
        return count, ratio, title, enabled, raw, legacy_false, truthy_text, explicit_default
""")
    index = models.ModelIndex.build([tmp_path])
    changes = python_checks.apply_runtime_api_migrations(mod, index, 20)
    text = (mod / "models.py").read_text(encoding="utf-8")
    assert "config.get_int(\"count\")" in text
    assert "config.get_float(\"ratio\", 1.5)" in text
    assert 'config.get_str("title", "Default")' in text
    assert 'config.get_bool("enabled")' in text
    assert 'config.get_str("raw")' in text
    assert 'config.set_int("attempts", 3)' in text
    assert 'config.set_param("dynamic", self.enabled)' in text
    assert 'config.get_str("legacy_false") == "False"' in text
    assert 'bool(config.get_str("truthy_text"))' in text
    assert 'config.get_str("explicit", False)' in text
    assert "if task.enabled:" in text
    assert len(changes) == 10
    messages = [
        message
        for _path, _line, _level, message in python_checks.check_module(
            mod, index, target_version=20
        )
    ]
    assert sum("set_param" in message for message in messages) == 1
    assert not any("get_param" in message for message in messages)


def test_odoo20_name_copy_suffix_is_prevented_for_custom_models(tmp_path):
    mod = addon(tmp_path, "custom", code="""from odoo import fields, models

class Line(models.Model):
    _name = "custom.line"
    _description = "Line"
    name = fields.Char(string="Name", required=True)
    x_name = fields.Char()

class Explicit(models.Model):
    _name = "custom.explicit"
    _description = "Explicit"
    name = fields.Char(copy=False)

class Computed(models.Model):
    _name = "custom.computed"
    _description = "Computed"
    name = fields.Char(compute="_compute_name")

class CallableTranslation(models.Model):
    _name = "custom.translated"
    _description = "Translated"
    x_name = fields.Char(translate=translate_xml)

class Extension(models.Model):
    _inherit = "res.partner"
    name = fields.Char(string="Contact Name")

class Child(models.Model):
    _name = "custom.child"
    _inherit = "custom.line"
    _description = "Child"
    name = fields.Char(string="Inherited Name")

class SqlView(models.Model):
    _name = "custom.sql.view"
    _description = "SQL View"
    _auto = False
    name = fields.Char()
""")
    index = models.ModelIndex.build([tmp_path])
    changes = python_checks.apply_runtime_api_migrations(mod, index, 20)
    text = (mod / "models.py").read_text(encoding="utf-8")
    assert 'name = fields.Char(string="Name", required=True, copy=True)' in text
    assert "x_name = fields.Char(copy=True)" in text
    assert "name = fields.Char(copy=False)" in text
    assert 'name = fields.Char(compute="_compute_name")' in text
    assert "x_name = fields.Char(translate=translate_xml)" in text
    assert 'name = fields.Char(string="Contact Name")' in text
    assert 'name = fields.Char(string="Inherited Name")' in text
    assert "class SqlView" in text and "    name = fields.Char()" in text
    assert len(changes) == 2
    assert not python_checks.apply_runtime_api_migrations(mod, index, 20)


def test_removed_fields_are_reported_in_qualified_raw_sql(tmp_path):
    mod = addon(tmp_path, "custom", code='''from odoo import models
from odoo.tools import SQL

class Report(models.Model):
    _name = "custom.report"
    _auto = False

    def _query(self):
        return SQL("""
            SELECT sm.id
              FROM stock_move AS sm
             WHERE sm.is_done = TRUE
        """)
''')
    index = models.ModelIndex.build([tmp_path])
    messages = list(
        python_checks.check_module(
            mod,
            index,
            target_version=20,
            removed_fields=[
                (
                    "stock.move",
                    "is_done",
                    "removed: test state in ('done', 'cancel')",
                )
            ],
        )
    )
    sql_issues = [item for item in messages if "stock.move.is_done" in item[3]]
    assert len(sql_issues) == 1
    assert sql_issues[0][2] == "error"
    assert sql_issues[0][1] == 12


def test_complex_translation_fstring_stays_manual(tmp_path, caplog):
    mod = addon(
        tmp_path,
        "custom",
        code='from odoo import _\nvalue = _(f"Total: {amount:.2f}")\n',
    )
    with caplog.at_level(logging.WARNING, logger="odoo_module_migrate"):
        quality.finish_module(mod)
    assert 'f"Total: {amount:.2f}"' in (mod / "models.py").read_text()
    assert "INT001" in caplog.text


def test_tree_to_list_keeps_user_facing_labels(tmp_path):
    mod = addon(
        tmp_path,
        "custom",
        code='LABEL = "EDI Tree View"\nMODE = {"view_mode": "tree,form"}\n',
    )
    replace_tree_with_list_in_views(
        logger=logging.getLogger("test"),
        module_path=mod,
        module_name="custom",
        manifest_path=mod / "__manifest__.py",
        migration_steps=(),
        tools=tools,
    )
    text = (mod / "models.py").read_text(encoding="utf-8")
    assert '"EDI Tree View"' in text
    assert '"view_mode": "list,form"' in text


def test_unique_non_circular_python_dependency_is_added(tmp_path):
    addon(tmp_path, "base", data=[])
    addon(
        tmp_path,
        "provider",
        ["base"],
        code='class Provided(Model):\n    _name = "provider.model"\n',
        data=[],
    )
    addon(
        tmp_path,
        "circular_provider",
        ["custom"],
        code='class Circular(Model):\n    _name = "circular.model"\n',
        data=[],
    )
    mod = addon(
        tmp_path,
        "custom",
        ["base"],
        code='def run(self):\n    self.env["provider.model"].search([])\n    self.env["circular.model"].search([])\n',
        data=[],
    )
    index = models.ModelIndex.build([tmp_path])
    additions = python_checks.apply_unambiguous_dependencies(mod, index)
    manifest = ast.literal_eval((mod / "__manifest__.py").read_text())
    assert additions == ["provider"]
    assert manifest["depends"] == ["base", "provider"]
    assert "circular_provider" not in manifest["depends"]


def test_enterprise_python_dependency_is_reported_but_not_added(tmp_path):
    addon(tmp_path, "base", data=[])
    provider = addon(
        tmp_path,
        "enterprise_feature",
        ["base"],
        code='class Feature(Model):\n    _name = "enterprise.feature"\n',
        data=[],
    )
    (provider / "__manifest__.py").write_text(
        repr(
            {
                "name": "Enterprise feature",
                "license": "OEEL-1",
                "depends": ["base"],
                "data": [],
            }
        ),
        encoding="utf-8",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["base"],
        code='def run(self):\n    self.env["enterprise.feature"].search([])\n',
        data=[],
    )
    index = models.ModelIndex.build([tmp_path])
    additions, manual = python_checks.apply_unambiguous_dependencies(
        mod, index, with_manual=True
    )
    manifest = ast.literal_eval((mod / "__manifest__.py").read_text())
    assert additions == []
    assert manifest["depends"] == ["base"]
    assert len(manual) == 1
    assert manual[0][2:] == (
        "enterprise_feature",
        "model enterprise.feature",
    )
    issues = list(python_checks.check_module(mod, index))
    assert len(issues) == 1
    assert issues[0][2] == "warning"
    assert "Enterprise provider enterprise_feature" in issues[0][3]


def test_base_search_override_does_not_create_enterprise_dependency(tmp_path):
    addon(tmp_path, "base", data=[])
    addon(
        tmp_path,
        "stock",
        ["base"],
        code='class Location(Model):\n    _name = "stock.location"\n',
        data=[],
    )
    barcode = addon(
        tmp_path,
        "stock_barcode",
        ["stock"],
        code='class Location(Model):\n    _inherit = "stock.location"\n    def _search(self, domain): pass\n',
        data=[],
    )
    (barcode / "__manifest__.py").write_text(
        repr(
            {
                "name": "Barcode",
                "license": "OEEL-1",
                "depends": ["stock"],
                "data": [],
            }
        ),
        encoding="utf-8",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["stock"],
        code='def run(self):\n    self.env["stock.location"]._search([])\n',
        data=[],
    )
    index = models.ModelIndex.build([tmp_path])
    additions, manual = python_checks.apply_unambiguous_dependencies(
        mod, index, with_manual=True
    )
    assert additions == []
    assert manual == []

    (barcode / "models.py").write_text(
        'class Location(Model):\n    _inherit = "stock.location"\n'
        "    def enterprise_scan(self): pass\n",
        encoding="utf-8",
    )
    (mod / "models.py").write_text(
        'def run(self):\n    self.env["stock.location"].enterprise_scan()\n',
        encoding="utf-8",
    )
    index = models.ModelIndex.build([tmp_path])
    additions, manual = python_checks.apply_unambiguous_dependencies(
        mod, index, with_manual=True
    )
    assert additions == []
    assert len(manual) == 1
    assert manual[0][2:] == (
        "stock_barcode",
        "method stock.location.enterprise_scan()",
    )


def test_mapped_relational_recordset_is_typed_for_field_renames(tmp_path):
    addon(tmp_path, "base", data=[])
    addon(
        tmp_path,
        "stock",
        ["base"],
        code='''class Picking(Model):
    _name = "stock.picking"
    move_line_ids = fields.One2many("stock.move.line")

class MoveLine(Model):
    _name = "stock.move.line"
    product_id = fields.Many2one("product.product")
    uom_id = fields.Many2one("uom.uom")
''',
        data=[],
    )
    mod = addon(
        tmp_path,
        "custom",
        ["stock"],
        code='''class Picking(Model):
    _inherit = "stock.picking"

    def quantities(self):
        for pack in self.mapped("move_line_ids").filtered(lambda x: x.product_id):
            pack.product_uom_id._compute_quantity(pack.quantity, pack.product_id.uom_id)
''',
        data=[],
    )
    index = models.ModelIndex.build([tmp_path])
    changes = python_checks.apply_field_renames(
        mod,
        index,
        {("stock.move.line", "product_uom_id"): "uom_id"},
    )
    assert len(changes) == 1
    assert "pack.uom_id._compute_quantity" in (mod / "models.py").read_text()


def test_invalid_escape_sequences_become_raw_strings(tmp_path, caplog):
    mod = addon(tmp_path, "custom", code="""from odoo import fields, models

class Input(models.Model):
    _name = "custom.input"
    _description = "Input"

    pattern = fields.Char(help='Ex: ^commande.*\\.txt$')
    mixed = fields.Char(help='a\\.b\\n')
    valid = fields.Char(help='a\\nb')
""")
    with caplog.at_level(logging.WARNING, logger="odoo_module_migrate"):
        quality.finish_module(mod)
    text = (mod / "models.py").read_text(encoding="utf-8")
    assert "help=r'Ex: ^commande.*\\.txt$'" in text
    assert "help='a\\.b\\n'" in text
    assert "help='a\\nb'" in text
    assert any("mixes valid and invalid" in r.message for r in caplog.records)


def test_manifest_drops_empty_data_and_dependency_dicts(tmp_path, caplog):
    mod = addon(tmp_path, "custom")
    (mod / "__manifest__.py").write_text(
        "{'name': 'Custom', 'depends': ['base'], 'data': [],"
        " 'external_dependencies': {'python': [], 'bin': ['wkhtmltopdf']},"
        " 'demo': [], 'assets': {}}\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="odoo_module_migrate"):
        quality.finish_module(mod, manifest_layout=True)
    data = ast.literal_eval((mod / "__manifest__.py").read_text(encoding="utf-8"))
    assert "data" not in data and "demo" not in data and "assets" not in data
    assert data["external_dependencies"] == {"bin": ["wkhtmltopdf"]}
    assert any("no 'author' key" in r.message for r in caplog.records)

    (mod / "__manifest__.py").write_text(
        "{'name': 'Custom', 'author': 'Me', 'external_dependencies': {'python': []}}\n",
        encoding="utf-8",
    )
    quality.finish_module(mod, manifest_layout=True)
    data = ast.literal_eval((mod / "__manifest__.py").read_text(encoding="utf-8"))
    assert "external_dependencies" not in data


def test_tracking_without_mail_thread_is_reported(tmp_path):
    addon(tmp_path, "mail", code="""from odoo import models

class Thread(models.AbstractModel):
    _name = "mail.thread"
    _description = "Thread"
""")
    mod = addon(tmp_path, "custom", ["mail"], code="""from odoo import fields, models

class Plain(models.Model):
    _name = "custom.plain"
    _description = "Plain"

    name = fields.Char(tracking=True)
    other = fields.Char(tracking=False)

class Tracked(models.Model):
    _name = "custom.tracked"
    _inherit = ["mail.thread"]
    _description = "Tracked"

    name = fields.Char(tracking=True)

class Extended(models.Model):
    _inherit = "custom.plain"

    code = fields.Char(tracking=10)

class Unknown(models.Model):
    _inherit = "outside.model"

    code = fields.Char(tracking=True)
""")
    index = models.ModelIndex.build([tmp_path])
    issues = list(models.check_tracking_without_mail(mod, index))
    names = sorted(message.split("'")[1] for _path, _line, message in issues)
    assert names == ["custom.plain.code", "custom.plain.name"]


def test_manifest_comment_of_dropped_key_is_removed(tmp_path):
    mod = addon(tmp_path, "custom")
    (mod / "__manifest__.py").write_text(
        "{\n"
        "    'name': 'Custom',\n"
        "    # business note on dependencies\n"
        "    'depends': ['base'],\n"
        "    # question about an alternative library\n"
        "    'external_dependencies': {\n"
        "    },\n"
        "    'data': [],  # inline note\n"
        "}\n",
        encoding="utf-8",
    )
    quality.finish_module(mod, manifest_layout=True)
    text = (mod / "__manifest__.py").read_text(encoding="utf-8")
    assert "# business note on dependencies" in text
    assert "alternative library" not in text
    assert "inline note" not in text


def test_default_author_fills_only_missing_author(tmp_path, caplog):
    mod = addon(tmp_path, "custom")
    with caplog.at_level(logging.WARNING, logger="odoo_module_migrate"):
        quality.finish_module(mod, manifest_layout=True, default_author="Team")
    data = ast.literal_eval((mod / "__manifest__.py").read_text(encoding="utf-8"))
    assert data["author"] == "Team"
    assert not any("'author'" in r.message for r in caplog.records)

    (mod / "__manifest__.py").write_text(
        "{'name': 'Custom', 'author': 'Original'}\n", encoding="utf-8"
    )
    quality.finish_module(mod, manifest_layout=True, default_author="Team")
    data = ast.literal_eval((mod / "__manifest__.py").read_text(encoding="utf-8"))
    assert data["author"] == "Original"


def test_manifest_normalizes_summary_and_removes_scaffold_description():
    from odoo_module_migrate.manifest import format_manifest

    original = '''{
    "name": "Purchase Owner",
    "summary": """
        Add   purchase
        owner.""",
    "description": """
        Long description of module's purpose
    """,
}
'''
    result = format_manifest(original)
    data = ast.literal_eval(result)
    assert data["summary"] == "Add purchase owner."
    assert "description" not in data
    assert format_manifest(result) == result


def test_translated_sql_constraint_message_is_prepared_for_official_script():
    source = '''from odoo import _, models

class Carrier(models.Model):
    _sql_constraints = [
        ("unique_code", "unique(code)", _("Le code doit être unique.")),
        ("positive", "CHECK(value > 0)", "Positive value required"),
    ]

def unrelated():
    return _("Keep this translation wrapper")
'''
    result = _unwrap_translated_constraint_messages(source)
    assignment = next(
        node
        for node in ast.walk(ast.parse(result))
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_sql_constraints"
            for target in node.targets
        )
    )
    assert ast.literal_eval(assignment.value.elts[0]) == (
        "unique_code",
        "unique(code)",
        "Le code doit être unique.",
    )
    assert '_("Keep this translation wrapper")' in result


def test_translated_sql_constraint_message_works_with_fallback(tmp_path, monkeypatch):
    source = '''from odoo import _, models
class Carrier(models.Model):
    _sql_constraints = [
        ("unique_code", "unique(code)", _("Le code doit être unique.")),
    ]
'''
    path = tmp_path / "models.py"
    path.write_text(source, encoding="utf-8")
    monkeypatch.setitem(tools.RUN_CONTEXT, "upgrade_code", None)
    upgrade_sql_constraints(
        logging.getLogger("test"),
        tmp_path,
        "custom",
        tmp_path / "__manifest__.py",
        [],
        tools,
    )
    result = path.read_text(encoding="utf-8")
    assert "_sql_constraints" not in result
    assert "_unique_code = models.Constraint(" in result
    assert "Le code doit être unique." in result


def test_toggle_active_view_buttons_are_migrated_only_when_direction_is_proven():
    source = '''<odoo><record id="view" model="ir.ui.view"><field name="arch" type="xml">
<form><header>
    <button type="object" name="toggle_active" invisible="not active" string="Archive"/>
    <button name="toggle_active" type="object" invisible="active" string="Restore"/>
    <button name="toggle_active" type="object" invisible="state != 'draft'"/>
</header></form>
</field></record></odoo>'''
    result, unresolved = _migrate_toggle_active_buttons(source)
    assert 'name="action_archive"' in result
    assert 'name="action_unarchive"' in result
    assert result.count('name="toggle_active"') == 1
    assert len(unresolved) == 1


def test_removed_toggle_active_python_call_is_reported(tmp_path):
    addon(tmp_path, "base", code='class Base(Model):\n    _name = "base"\n')
    mod = addon(
        tmp_path,
        "custom",
        ["base"],
        code='''class Item(Model):
    _name = "custom.item"

    def archive_or_restore(self):
        self.toggle_active()
''',
    )
    index = models.ModelIndex.build([tmp_path])
    messages = [
        message
        for _path, _line, _level, message in python_checks.check_module(
            mod, index, target_version=20
        )
    ]
    assert any("toggle_active() does not exist" in message for message in messages)


def test_final_report_rechecks_text_errors_and_ignores_unloaded_python(tmp_path):
    mod = addon(
        tmp_path,
        "custom",
        code="from odoo import models\n",
    )
    (mod / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    orphan = mod / "orphan.py"
    orphan.write_text("from odoo.osv import expression\n", encoding="utf-8")
    migration = Migration(
        tmp_path,
        "19.0",
        "20.0",
        ["custom"],
        commit_enabled=False,
        pre_commit=False,
    )
    migration.report_collector = ReportCollector([("custom", mod)])
    module_report = migration.report_collector.reports["custom"]
    message = (
        "[20] The odoo.osv package was removed: use odoo.fields.Domain "
        "(Domain.AND / Domain.OR...)"
    )
    module_report.entries.extend(
        [
            Entry("ERROR", message, "models.py", 1),
            Entry("ERROR", message, "orphan.py", 1),
        ]
    )

    migration._reconcile_text_rule_diagnostics()

    assert not [entry for entry in module_report.entries if entry.message == message]
    (mod / "models.py").write_text(
        "from odoo.osv import expression\n", encoding="utf-8"
    )
    migration._reconcile_text_rule_diagnostics()
    remaining = [entry for entry in module_report.entries if entry.message == message]
    assert len(remaining) == 1
    assert (remaining[0].file, remaining[0].line) == ("models.py", 1)


def test_unimported_python_file_is_reported_once(tmp_path, caplog):
    mod = addon(tmp_path, "custom", code="VALUE = 1\n")
    (mod / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    orphan = mod / "orphan.py"
    orphan.write_text("VALUE = 2\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="odoo_module_migrate"):
        quality.finish_module(mod)

    warnings = [
        record.message
        for record in caplog.records
        if "not reachable from the addon's __init__.py" in record.message
    ]
    assert len(warnings) == 1
    assert str(orphan) in warnings[0]


def test_override_signature_is_synchronized_from_target(tmp_path):
    addon(tmp_path, "base", code="class Base(Model):\n    _name = 'base'\n")
    addon(
        tmp_path,
        "sale",
        ["base"],
        """class SaleOrder(Model):
    _name = "sale.order"

    def _create_invoices(self, final=False, grouped=False):
        return self
""",
    )
    custom = addon(
        tmp_path,
        "custom",
        ["sale"],
        """class SaleOrder(Model):
    _inherit = "sale.order"

    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped, final, date)
        return moves if final else self
""",
    )
    index = models.ModelIndex.build([tmp_path])

    before = [
        message
        for _path, _line, _level, message in python_checks.check_module(custom, index)
        if "override is incompatible" in message
    ]
    assert len(before) == 1
    assert "target parameters are reordered" in before[0]
    assert "passes 3 positional arguments" in before[0]

    changes = python_checks.apply_override_signature_migrations(custom, index)

    assert len(changes) == 1
    migrated = (custom / "models.py").read_text(encoding="utf-8")
    assert "def _create_invoices(self, final=False, grouped=False):" in migrated
    assert "super()._create_invoices(final=final, grouped=grouped)" in migrated
    ast.parse(migrated)
    assert not [
        message
        for _path, _line, _level, message in python_checks.check_module(custom, index)
        if "override is incompatible" in message
    ]

    keyword_custom = addon(
        tmp_path,
        "keyword_custom",
        ["sale"],
        """class SaleOrder(Model):
    _inherit = "sale.order"

    def _create_invoices(self, grouped=False, final=False, date=None):
        return super()._create_invoices(grouped=grouped, final=final, date=date)
""",
    )
    keyword_index = models.ModelIndex.build([tmp_path])
    assert len(
        python_checks.apply_override_signature_migrations(
            keyword_custom, keyword_index
        )
    ) == 1
    keyword_migrated = (keyword_custom / "models.py").read_text(encoding="utf-8")
    assert "def _create_invoices(self, final=False, grouped=False):" in keyword_migrated
    assert "super()._create_invoices(final=final, grouped=grouped)" in keyword_migrated


def test_complex_override_signature_is_reported_without_rewrite(tmp_path):
    addon(tmp_path, "base", code="class Base(Model):\n    _name = 'base'\n")
    addon(
        tmp_path,
        "provider",
        ["base"],
        """class Item(Model):
    _name = "x.item"

    def process(self, value, *, strict=False):
        return value
""",
    )
    custom = addon(
        tmp_path,
        "custom",
        ["provider"],
        """class Item(Model):
    _inherit = "x.item"

    def process(self, strict=False, value=None):
        return super().process(strict, value)
""",
    )
    original = (custom / "models.py").read_text(encoding="utf-8")
    index = models.ModelIndex.build([tmp_path])

    issues = [
        (level, message)
        for _path, _line, level, message in python_checks.check_module(custom, index)
        if "override is incompatible" in message
    ]

    assert len(issues) == 1 and issues[0][0] == "error"
    assert not python_checks.apply_override_signature_migrations(custom, index)
    assert (custom / "models.py").read_text(encoding="utf-8") == original


def test_keyword_only_target_with_permissive_override_is_a_warning(tmp_path):
    addon(tmp_path, "base", code="class Base(Model):\n    _name = 'base'\n")
    addon(
        tmp_path,
        "provider",
        ["base"],
        """class Item(Model):
    _name = "x.item"
    def process(self, *, previous=False):
        return previous
""",
    )
    custom = addon(
        tmp_path,
        "custom",
        ["provider"],
        """class Item(Model):
    _inherit = "x.item"
    def process(self, previous=False):
        return super().process(previous=previous)
""",
    )
    issues = [
        (level, message)
        for _path, _line, level, message in python_checks.check_module(
            custom, models.ModelIndex.build([tmp_path])
        )
        if "keyword-only" in message
    ]
    assert len(issues) == 1
    assert issues[0][0] == "warning"
    assert "should align its signature" in issues[0][1]


def test_oca_maintainers_is_a_known_manifest_key():
    from odoo_module_migrate.manifest import inspect_keys

    unknown, concatenated = inspect_keys(
        "{'name': 'Example', 'maintainers': ['alice', 'bob']}"
    )
    assert unknown == []
    assert concatenated == []


def test_test_values_dict_uses_model_proven_field_rename(tmp_path):
    addon(tmp_path, "base", code="class Base(Model):\n    _name = 'base'\n")
    addon(
        tmp_path,
        "purchase",
        ["base"],
        """class Line(Model):
    _name = "purchase.order.line"
    product_id = fields.Many2one("product.product")
    product_qty = fields.Float()
    uom_id = fields.Many2one("uom.uom")
    price_unit = fields.Float()
    date_planned = fields.Datetime()
""",
    )
    custom = addon(tmp_path, "custom", ["purchase"], "VALUE = 1\n")
    tests = custom / "tests"
    tests.mkdir()
    path = tests / "test_order.py"
    path.write_text(
        """def values(product, qty):
    return {
        "product_id": product.id,
        "product_qty": qty,
        "product_uom_id": product.uom_id.id,
        "price_unit": 100,
        "date_planned": fields.Datetime.now(),
    }
""",
        encoding="utf-8",
    )
    index = models.ModelIndex.build([tmp_path])

    changes = python_checks.apply_field_renames(
        custom,
        index,
        {("purchase.order.line", "product_uom_id"): "uom_id"},
    )

    assert len(changes) == 1
    assert '"uom_id": product.uom_id.id' in path.read_text(encoding="utf-8")


def test_base_common_privileges_are_preserved_for_odoo20(tmp_path):
    module = tmp_path / "custom"
    tests = module / "tests"
    tests.mkdir(parents=True)
    path = tests / "common.py"
    path.write_text(
        """from odoo.addons.base.tests.common import BaseCommon


class CustomCommon(BaseCommon):
    \"\"\"Shared privileged setup.\"\"\"

    def helper(self):
        return self.env.company
""",
        encoding="utf-8",
    )

    changes = python_checks.apply_base_common_compatibility(module)

    assert len(changes) == 1
    migrated = path.read_text(encoding="utf-8")
    assert migrated.count("_test_user_groups = None") == 1
    ast.parse(migrated)
    assert not python_checks.apply_base_common_compatibility(module)


def test_base_common_attribute_is_inserted_before_first_decorator(tmp_path):
    module = tmp_path / "custom"
    tests = module / "tests"
    tests.mkdir(parents=True)
    path = tests / "common.py"
    path.write_text(
        """from odoo.addons.base.tests.common import BaseCommon

class CustomCommon(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
""",
        encoding="utf-8",
    )

    python_checks.apply_base_common_compatibility(module)

    migrated = path.read_text(encoding="utf-8")
    assert migrated.index("_test_user_groups") < migrated.index("@classmethod")
    ast.parse(migrated)


def test_selected_merged_module_is_reported(tmp_path, caplog):
    module = tmp_path / "old_module"
    module.mkdir()
    manifest = module / "__manifest__.py"
    manifest.write_text("{'depends': []}\n", encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="odoo_module_migrate"):
        BaseMigrationScript().handle_deprecated_modules(
            manifest,
            [["old_module", "merged", "new_module"]],
            module_name="old_module",
        )

    assert "is merged into 'new_module'" in caplog.text


def test_stale_merged_sibling_is_reported_for_later_start_version(tmp_path, caplog):
    for name in ("account_payment_mode", "account_payment_partner"):
        module = tmp_path / name
        module.mkdir()
        (module / "__manifest__.py").write_text(
            f"{{'name': {name!r}, 'depends': []}}\n", encoding="utf-8"
        )
    migration = Migration(
        tmp_path,
        "19.0",
        "20.0",
        module_names=["account_payment_mode"],
        commit_enabled=False,
        pre_commit=False,
        write_report=False,
    )

    with caplog.at_level(logging.ERROR, logger="odoo_module_migrate"):
        migration._check_repository_merged_modules()

    assert "account_payment_partner' is merged into 'account_payment_mode" in caplog.text


def test_simple_sql_report_hooks_are_migrated_to_tablesql(tmp_path):
    from odoo_module_migrate.migration_scripts.python_scripts.migrate_190_200.report_table_sql import (
        migrate_report_table_sql,
    )

    module = tmp_path / "custom"
    module.mkdir()
    sale = module / "sale_report.py"
    sale.write_text(
        '''from odoo import models

class Report(models.Model):
    _inherit = "sale.report"

    def _select_additional_fields(self):
        res = super()._select_additional_fields()
        res["type_id"] = "s.type_id"
        return res

    def _group_by_sale(self):
        res = super()._group_by_sale()
        res += ", s.type_id"
        return res
''',
        encoding="utf-8",
    )
    invoice = module / "invoice_report.py"
    invoice.write_text(
        '''from odoo import models

class Report(models.Model):
    _inherit = "account.invoice.report"

    def _select(self):
        result = super()._select()
        result += """, move.sale_type_id as sale_type_id"""
        return result
''',
        encoding="utf-8",
    )

    migrate_report_table_sql(
        module, tools, logging.getLogger("odoo_module_migrate")
    )

    sale_text = sale.read_text(encoding="utf-8")
    invoice_text = invoice.read_text(encoding="utf-8")
    assert "def _select_dict(self, table):" in sale_text
    assert '"type_id": table.order_id.type_id' in sale_text
    assert "def _groupby_list(self, table):" in sale_text
    assert "[table.order_id.type_id]" in sale_text
    assert "from odoo.tools import SQL" in invoice_text
    assert "def _select_list(self, table):" in invoice_text
    assert 'SQL("%s AS sale_type_id", table.move_id.sale_type_id)' in invoice_text
    ast.parse(sale_text)
    ast.parse(invoice_text)


def test_access_fallback_preserves_manifest_layout_and_flattens_domain(tmp_path):
    from odoo_module_migrate.migration_scripts.migrate_190_200 import (
        convert_access_to_ir_access,
    )

    module = tmp_path / "custom"
    security = module / "security"
    security.mkdir(parents=True)
    manifest = module / "__manifest__.py"
    original = '''{
    "name": "Custom",
    "data": ["security/ir.model.access.csv",
             "security/rules.xml"],
}
'''
    manifest.write_text(original, encoding="utf-8")
    (security / "ir.model.access.csv").write_text(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "access_x,X,model_x,base.group_user,1,1,0,0\n",
        encoding="utf-8",
    )
    (security / "rules.xml").write_text(
        """<odoo><record id="rule_x" model="ir.rule">
<field name="name">X restriction</field><field name="model_id" ref="model_x"/>
<field name="domain_force">[
    '|', ('company_id', '=', False),
    ('company_id', 'in', company_ids)
]</field></record></odoo>""",
        encoding="utf-8",
    )

    convert_access_to_ir_access(
        logging.getLogger("odoo_module_migrate"),
        module,
        "custom",
        manifest,
        [],
        tools,
    )

    rewritten = manifest.read_text(encoding="utf-8")
    assert '"data": ["security/ir.access.csv",\n' in rewritten
    assert ast.literal_eval(rewritten)["data"] == [
        "security/ir.access.csv",
        "security/rules.xml",
    ]
    rows = (security / "ir.access.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 3
    assert "company_ids" in rows[1]
    assert not (security / "ir.model.access.csv").exists()


def test_access_fallback_drops_external_acl_override_and_stale_manifest_entry(
    tmp_path, caplog
):
    from odoo_module_migrate.migration_scripts.migrate_190_200 import (
        convert_access_to_ir_access,
    )

    module = tmp_path / "custom"
    security = module / "security"
    security.mkdir(parents=True)
    manifest = module / "__manifest__.py"
    manifest.write_text(
        "{'data': ['security/ir.model.access.csv', 'views.xml']}\n",
        encoding="utf-8",
    )
    source = security / "ir.model.access.csv"
    source.write_text(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "account.access_method,External,account.model_method,account.group_manager,1,1,1,1\n",
        encoding="utf-8",
    )

    tools.RUN_CONTEXT["upgrade_code"] = True
    try:
        with caplog.at_level(logging.ERROR, logger="odoo_module_migrate"):
            convert_access_to_ir_access(
                logging.getLogger("odoo_module_migrate"),
                module,
                "custom",
                manifest,
                [],
                tools,
            )
    finally:
        tools.RUN_CONTEXT.clear()

    assert "belongs to external module account" in caplog.text
    assert not source.exists()
    assert not (security / "ir.access.csv").exists()
    assert ast.literal_eval(manifest.read_text(encoding="utf-8"))["data"] == [
        "views.xml"
    ]


def test_access_fallback_keeps_local_rows_when_external_override_is_mixed(
    tmp_path, caplog
):
    from odoo_module_migrate.migration_scripts.migrate_190_200 import (
        convert_access_to_ir_access,
    )

    module = tmp_path / "custom"
    security = module / "security"
    security.mkdir(parents=True)
    manifest = module / "__manifest__.py"
    manifest.write_text(
        "{'data': ['security/ir.model.access.csv']}\n", encoding="utf-8"
    )
    (security / "ir.model.access.csv").write_text(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "access_local,Local,model_local,base.group_user,1,0,0,0\n"
        "account.access_method,External,account.model_method,account.group_manager,1,1,1,1\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.ERROR, logger="odoo_module_migrate"):
        convert_access_to_ir_access(
            logging.getLogger("odoo_module_migrate"),
            module,
            "custom",
            manifest,
            [],
            tools,
        )

    target = (security / "ir.access.csv").read_text(encoding="utf-8")
    assert "access_local" in target
    assert "account.access_method" not in target
    assert ast.literal_eval(manifest.read_text(encoding="utf-8"))["data"] == [
        "security/ir.access.csv"
    ]
