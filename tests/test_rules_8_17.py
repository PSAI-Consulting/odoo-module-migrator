# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Unit tests of the rules of the 8.0 → 17.0 steps."""

import glob

import yaml

from odoo_module_migrate import manifest

SCRIPTS = "odoo_module_migrate/migration_scripts"


def _module_rules(step):
    rules = []
    for path in sorted(glob.glob(f"{SCRIPTS}/deprecated_modules/{step}/*.yaml")):
        rules += yaml.safe_load(open(path, encoding="utf-8")) or []
    return rules


def test_module_rules_160_170():
    rules = _module_rules("migrate_160_170")
    depends = ["event_barcode", "sale_enterprise", "account_reconcile_wizard", "note", "stock"]
    new, messages = manifest.apply_module_rules(depends, rules)
    # curated.yaml wins over the "removed" of modules.yaml
    assert new == ["event", "sale", "account_accountant", "project_todo", "stock"]
    assert all(level == "info" for level, _msg in messages), messages
    assert manifest.apply_module_rules(new, rules) == (new, [])
    # not renamed into the test module l10n_br_test_avatax_sale
    new, messages = manifest.apply_module_rules(["l10n_br_avatax_sale"], rules)
    assert new == ["l10n_br_avatax_sale"]
    assert [level for level, _msg in messages] == ["error"]


ATTRS_XML = """<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- <field name="x" attrs="{'invisible': [('a', '=', 1)]}"/> -->
    <record id="view_form" model="ir.ui.view">
        <field name="model">x.model</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <button name="action_confirm" states="draft,sent" type="object"/>
                    <button
                        name="action_cancel"
                        type="object"
                        states="draft"
                        attrs="{'invisible': [('locked', '=', True)]}"
                    />
                </header>
                <field
                    name="partner_id"
                    attrs="{'readonly': [('state', '!=', 'draft')], 'required': ['|', ('a', '=', False), ('b', '&lt;', 3)]}"
                />
                <field name="secret" invisible="1" attrs="{'invisible': [('a', '=', 1)]}"/>
                <field name="note" readonly="0" attrs="{'readonly': [('x_ids', '=', [])]}"/>
                <field name="ref" attrs="{'invisible': [('name', 'ilike', 'x')]}"/>
            </form>
        </field>
    </record>
    <record id="view_form_inherit" model="ir.ui.view">
        <field name="inherit_id" ref="view_form"/>
        <field name="arch" type="xml">
            <field name="partner_id" position="attributes">
                <attribute name="attrs">{'invisible': [('a', '=', 1)], 'readonly': True}</attribute>
            </field>
            <button name="action_confirm" position="attributes">
                <attribute name="states">draft</attribute>
            </button>
        </field>
    </record>
    <record id="action" model="ir.actions.act_window">
        <field name="context">{'attrs': 1}</field>
    </record>
    <template id="fragment">
        <group attrs="{'invisible': [('reason', '=', False)]}"/>
    </template>
</odoo>
"""

ATTRS_EXPECTED = """<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- <field name="x" attrs="{'invisible': [('a', '=', 1)]}"/> -->
    <record id="view_form" model="ir.ui.view">
        <field name="model">x.model</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <button name="action_confirm" invisible="state not in ('draft', 'sent')" type="object"/>
                    <button
                        name="action_cancel"
                        type="object"
                        invisible="locked and state != 'draft'"
                    />
                </header>
                <field
                    name="partner_id"
                    readonly="state != 'draft'"
                    required="(not a or b &lt; 3)"
                />
                <field name="secret" invisible="1"/>
                <field name="note" readonly="not x_ids"/>
                <field name="ref" attrs="{'invisible': [('name', 'ilike', 'x')]}"/>
            </form>
        </field>
    </record>
    <record id="view_form_inherit" model="ir.ui.view">
        <field name="inherit_id" ref="view_form"/>
        <field name="arch" type="xml">
            <field name="partner_id" position="attributes">
                <attribute name="invisible">a == 1</attribute>
                <attribute name="readonly">True</attribute>
            </field>
            <button name="action_confirm" position="attributes">
                <attribute name="invisible">state != 'draft'</attribute>
            </button>
        </field>
    </record>
    <record id="action" model="ir.actions.act_window">
        <field name="context">{'attrs': 1}</field>
    </record>
    <template id="fragment">
        <group invisible="not reason"/>
    </template>
</odoo>
"""


def test_attrs_states_to_attributes(tmp_path, caplog):
    import logging

    from odoo_module_migrate.migration_scripts.migrate_160_170 import (
        _move_attrs_to_attributes_view,
    )

    logger = logging.getLogger("test")
    path = tmp_path / "view.xml"
    path.write_text(ATTRS_XML, encoding="utf-8")
    _move_attrs_to_attributes_view(logger, path)
    assert path.read_text(encoding="utf-8") == ATTRS_EXPECTED
    # 'ilike' has no python equivalent: kept and reported
    assert "line 23: attrs/states of <field> not converted" in caplog.text
    # second pass: no change
    _move_attrs_to_attributes_view(logger, path)
    assert path.read_text(encoding="utf-8") == ATTRS_EXPECTED


HOOKS_PY = '''from odoo import SUPERUSER_ID, api, fields

_logger = None


def pre_init_hook(cr):
    """Prepopulate"""
    cr.execute("SELECT 1")


def post_init_hook(cr, registry, vals=None):
    with api.Environment.manage():
        env = api.Environment(cr, SUPERUSER_ID, {})
        env.ref("sale.rule").active = False


def uninstall_hook(cr, registry):
    registry["res.partner"]._fields


def helper(cr):
    env = api.Environment(cr, SUPERUSER_ID, {})
    return fields.Date.today(), env
'''

HOOKS_EXPECTED = '''from odoo import SUPERUSER_ID, api, fields

_logger = None


def pre_init_hook(env):
    """Prepopulate"""
    cr = env.cr
    cr.execute("SELECT 1")


def post_init_hook(env):
    env.ref("sale.rule").active = False


def uninstall_hook(cr, registry):
    registry["res.partner"]._fields


def helper(cr):
    env = api.Environment(cr, SUPERUSER_ID, {})
    return fields.Date.today(), env
'''


def test_init_hooks_env():
    from odoo_module_migrate.migration_scripts.python_scripts.migrate_160_170 import (
        init_hooks,
    )

    hooks = {"pre_init_hook", "post_init_hook", "uninstall_hook"}
    new, errors = init_hooks._rewrite(HOOKS_PY, hooks)
    assert new == HOOKS_EXPECTED
    # registry used: reported, not changed
    assert errors == [("uninstall_hook", 16, "uses registry")]
    assert init_hooks._rewrite(new, hooks) == (new, [("uninstall_hook", 16, "uses registry")])
    # SUPERUSER_ID / api no longer used: import dropped
    text = HOOKS_PY.split("\n\n\ndef uninstall_hook")[0] + "\n"
    new, errors = init_hooks._rewrite(text, hooks)
    assert new.startswith("from odoo import fields\n\n_logger")
    assert not errors


MANAGE_PY = '''from odoo import api


def run(env):
    with api.Environment.manage():
        env.cr.execute("""
            SELECT 1
        """)
        if env:
            return 1
    with api.Environment.manage() as manager:
        return manager
'''

MANAGE_EXPECTED = '''from odoo import api


def run(env):
    env.cr.execute("""
            SELECT 1
        """)
    if env:
        return 1
    with api.Environment.manage() as manager:
        return manager
'''


def test_environment_manage_removed():
    from odoo_module_migrate.migration_scripts.python_scripts.migrate_160_170 import (
        environment_manage,
    )

    new, unconverted = environment_manage._rewrite(MANAGE_PY)
    assert new == MANAGE_EXPECTED
    assert unconverted == [10]
    assert environment_manage._rewrite(new) == (new, [10])


def _yaml_rules(kind, step, ext):
    rules = {}
    for path in sorted(glob.glob(f"{SCRIPTS}/{kind}/{step}/*.yaml")):
        rules.update((yaml.safe_load(open(path, encoding="utf-8")) or {}).get(ext, {}))
    return rules


def _matching(rules, text):
    import re

    return sorted(pattern for pattern in rules if re.search(pattern, text))


def test_core_api_160_170():
    errors = _yaml_rules("text_errors", "migrate_160_170", ".py")
    warnings = _yaml_rules("text_warnings", "migrate_160_170", ".py")
    old = (
        "    state = fields.Selection(READONLY_STATES)\n"
        "    date = fields.Date(readonly=True, states={'draft': [('readonly', False)]})\n"
        "    ref = fields.Char(states=READONLY_STATES)\n"
        "    def name_get(self):\n"
        "        return super().name_get()\n"
    )
    assert len(_matching(errors, old)) == 2
    assert _matching(warnings, old) == [r"\.name_get\(\)"]
    migrated = (
        "    states = self.mapped('state')\n"
        "    self._filter(states=states)\n"
        "    def _compute_display_name(self):\n"
        "        record.display_name = record.name\n"
    )
    assert not _matching(errors, migrated) and not _matching(warnings, migrated)


EXPENSE_PY = '''from odoo import api, fields, models


class HrExpense(models.Model):
    _inherit = "hr.expense"

    x_total = fields.Float(compute="_compute_x_total")

    @api.depends("unit_amount", "total_amount", "total_amount_company")
    def _compute_x_total(self):
        for expense in self:
            expense.x_total = expense.unit_amount + expense.amount_tax


class ProjectTask(models.Model):
    _inherit = "project.task"

    def _x(self):
        return self.planned_hours
'''


def test_curated_renames_160_170(tmp_path, caplog):
    import logging

    from odoo_module_migrate.migration_scripts.migrate_160_170 import MigrationScript

    module = tmp_path / "x_mod"
    module.mkdir()
    (module / "__manifest__.py").write_text("{'name': 'x', 'depends': ['hr_expense', 'project']}")
    (module / "models.py").write_text(EXPENSE_PY)
    script = MigrationScript()
    script.parse_rules()
    with caplog.at_level(logging.WARNING):
        script.handle_fields(module)
    py = (module / "models.py").read_text()
    assert '@api.depends("price_unit", "total_amount", "total_amount_company")' in py
    assert "expense.price_unit + expense.tax_amount_currency" in py
    assert "return self.allocated_hours" in py
    # name swap: total_amount kept, total_amount_company reported with its replacement
    assert any(
        "hr.expense.total_amount_company was removed" in r.getMessage()
        and "renamed total_amount" in r.getMessage()
        for r in caplog.records
    )
    script.handle_fields(module)
    assert (module / "models.py").read_text() == py


def test_removed_views_160_170():
    errors = _yaml_rules("text_errors", "migrate_160_170", ".xml")
    old = '<field name="inherit_id" ref="account.account_invoice_onboarding_panel"/>'
    assert len(_matching(errors, old)) == 1
    assert not _matching(errors, '<field name="inherit_id" ref="account.view_move_form"/>')


def test_module_rules_150_160():
    rules = _module_rules("migrate_150_160")
    depends = ["gift_card", "coupon", "l10n_nl_report_intrastat", "l10n_de_sale", "mail"]
    new, messages = manifest.apply_module_rules(depends, rules)
    assert new == ["loyalty", "l10n_nl_intrastat", "l10n_din5008_sale", "mail"]
    assert all(level == "info" for level, _msg in messages), messages
    assert manifest.apply_module_rules(new, rules) == (new, [])


def test_openupgrade_dk_rename_170_180(tmp_path):
    from odoo_module_migrate.migration_scripts.migrate_170_180 import MigrationScript

    module = tmp_path / "x_mod"
    module.mkdir()
    (module / "__manifest__.py").write_text("{'name': 'x', 'depends': ['l10n_dk']}")
    (module / "models.py").write_text(
        "from odoo import models\n\n\nclass AccountMove(models.Model):\n"
        '    _inherit = "account.move"\n\n    def _x(self):\n'
        "        return self.l10n_dk_currency_rate_at_transaction\n"
    )
    script = MigrationScript()
    script.parse_rules()
    script.handle_fields(module)
    assert "return self.invoice_currency_rate\n" in (module / "models.py").read_text()


def _apply(kind, step, ext, text):
    import re

    for pattern, repl in _yaml_rules(kind, step, ext).items():
        text = re.sub(pattern, repl or "", text)
    return text


def test_orm_deprecations_150_160_and_160_170():
    text = (
        "xid = rec.get_xml_id()\n"
        "names = self.env['res.partner'].fields_get_keys() + ['x']\n"
        "self.flush()\n"
        "self.env['x'].invalidate_cache(['a'])\n"
        "f.flush()\n"
        "self._refresh()\n"
    )
    for step in ("migrate_150_160", "migrate_160_170"):
        new = _apply("text_replaces", step, ".py", text)
        assert "xid = rec.get_external_id()\n" in new
        assert "names = list(self.env['res.partner']._fields) + ['x']\n" in new
        assert _apply("text_replaces", step, ".py", new) == new
    warnings = _yaml_rules("text_warnings", "migrate_150_160", ".py")
    errors = _yaml_rules("text_errors", "migrate_160_170", ".py")
    for rules in (warnings, errors):
        assert [line for line in text.splitlines() if _matching(rules, line)] == [
            "self.flush()", "self.env['x'].invalidate_cache(['a'])",
        ]


def test_field_rules_follow_renamed_model_150_160(tmp_path):
    """OpenUpgrade 16.0 renames coupon.program fields under the old model name,
    while coupon.program is renamed loyalty.program in the same step: the model
    is renamed in the files first, the field rules must still apply."""
    from odoo_module_migrate.migration_scripts.migrate_150_160 import MigrationScript

    module = tmp_path / "x_mod"
    module.mkdir()
    (module / "__manifest__.py").write_text("{'name': 'x', 'depends': ['coupon']}")
    (module / "models.py").write_text(
        "from odoo import models\n\n\nclass Program(models.Model):\n"
        '    _inherit = "loyalty.program"\n\n    def _x(self):\n'
        "        return self.promo_code_usage, self.maximum_use_number\n"
    )
    script = MigrationScript()
    script.parse_rules()
    script.handle_fields(module)
    text = (module / "models.py").read_text()
    assert "return self.trigger, self.max_usage" in text
    script.handle_fields(module)
    assert (module / "models.py").read_text() == text


def test_removed_api_160_170():
    errors = _yaml_rules("text_errors", "migrate_160_170", ".py")
    assert _matching(errors, "from odoo.exceptions import UserError, Warning")
    assert _matching(errors, "raise exceptions.except_orm('x')")
    assert not _matching(errors, "from odoo.exceptions import UserError, ValidationError")
    assert not _matching(errors, "import warnings\nwarnings.warn('x', UserWarning)")


def test_module_rules_140_150():
    rules = _module_rules("migrate_140_150")
    new, messages = manifest.apply_module_rules(
        ["helpdesk_sale_timesheet_edit", "l10n_ch_qriban", "website_calendar", "sale"], rules
    )
    assert new == ["helpdesk_sale_timesheet", "l10n_ch", "website_appointment", "sale"]
    assert all(level == "info" for level, _msg in messages), messages
    assert manifest.apply_module_rules(new, rules) == (new, [])


def test_rules_140_150():
    errors = _yaml_rules("text_errors", "migrate_140_150", ".py")
    assert _matching(errors, "return http.local_redirect('/web')")
    assert not _matching(errors, "return request.redirect('/web')")
    assert not _matching(errors, "html = html_escape(x)")
    rules = []
    for path in sorted(glob.glob(f"{SCRIPTS}/renamed_fields/migrate_140_150/*.yaml")):
        rules += yaml.safe_load(open(path, encoding="utf-8")) or []
    assert ["crm.lead", "meeting_count", "calendar_event_count"] in [r[:3] for r in rules]


def test_savepointcase_140_150():
    text = (
        "from odoo.tests.common import SavepointCase, TransactionCase\n"
        "from odoo.tests import SavepointCase\n"
        "class TestX(SavepointCase):\n"
        "class TestY(HttpSavepointCase):\n"
    )
    new = _apply("text_replaces", "migrate_140_150", ".py", text)
    assert new == (
        "from odoo.tests.common import TransactionCase\n"
        "from odoo.tests import TransactionCase\n"
        "class TestX(TransactionCase):\n"
        "class TestY(HttpSavepointCase):\n"
    )
    assert _apply("text_replaces", "migrate_140_150", ".py", new) == new


SHORTCUTS_XML = """<odoo>
    <!-- <report id="old" model="x" name="x" string="x"/> -->
    <act_window id="action_a" name="A &amp; B" res_model="res.partner"
        binding_model="sale.order" binding_type="report" binding_views="list"/>
    <act_window id="action_b" name="B" res_model="x.unknown" binding_model="x.unknown.model"/>
    <act_window id="action_c" name="C" res_model="x.own" binding_model="x.own"/>
</odoo>
"""


def test_report_act_window_to_record_130_140(tmp_path, caplog):
    import logging

    from odoo_module_migrate.migration_scripts.migrate_130_140 import _reformat_file

    path = tmp_path / "views.xml"
    path.write_text(SHORTCUTS_XML, encoding="utf-8")
    logger = logging.getLogger("test")
    _reformat_file(path, {"x.own"}, "my_module", logger)
    text = path.read_text(encoding="utf-8")
    assert "<!-- <report id=\"old\"" in text
    assert (
        '    <record id="action_a" model="ir.actions.act_window">\n'
        '        <field name="name">A &amp; B</field>\n'
        '        <field name="res_model">res.partner</field>\n'
        '        <field name="binding_model_id" ref="sale.model_sale_order"/>\n'
        '        <field name="binding_type">report</field>\n'
        '        <field name="binding_view_types">list</field>\n'
        "    </record>\n"
    ) in text
    # model of another unknown module: kept and reported
    assert '<act_window id="action_b"' in text
    assert "module of model x.unknown.model unknown" in caplog.text
    # model of the module itself: local xmlid
    assert '<field name="binding_model_id" ref="my_module.model_x_own"/>' in text
    _reformat_file(path, {"x.own"}, "my_module", logger)
    assert path.read_text(encoding="utf-8") == text


def test_module_rules_130_140():
    rules = _module_rules("migrate_130_140")
    new, messages = manifest.apply_module_rules(["l10n_cn_standard", "ocn_client", "sale"], rules)
    assert new == ["l10n_cn", "mail_mobile", "sale"]
    assert manifest.apply_module_rules(new, rules) == (new, [])


def test_blocked_swaps_130_140(tmp_path, caplog):
    import logging

    from odoo_module_migrate.migration_scripts.migrate_130_140 import MigrationScript

    module = tmp_path / "x_mod"
    module.mkdir()
    (module / "__manifest__.py").write_text("{'name': 'x', 'depends': ['crm', 'account']}")
    text = (
        "from odoo import models\n\n\nclass Lead(models.Model):\n"
        '    _inherit = "crm.lead"\n\n    def _x(self):\n'
        "        return self.planned_revenue, self.expected_revenue\n\n\n"
        "class Move(models.Model):\n"
        '    _inherit = "account.move"\n\n    def _y(self):\n'
        "        return self.type, self.invoice_payment_state\n"
    )
    (module / "models.py").write_text(text)
    script = MigrationScript()
    script.parse_rules()
    with caplog.at_level(logging.WARNING):
        script.handle_fields(module)
    new = (module / "models.py").read_text()
    assert "return self.planned_revenue, self.expected_revenue\n" in new
    assert "return self.move_type, self.payment_state\n" in new
    assert any("crm.lead.planned_revenue was removed" in r.getMessage() for r in caplog.records)
    script.handle_fields(module)
    assert (module / "models.py").read_text() == new


def test_core_api_130_140():
    errors = _yaml_rules("text_errors", "migrate_130_140", ".py")
    assert _matching(errors, "lines = self.resolve_2many_commands('line_ids', cmds)")
    assert not _matching(errors, "lines = self.line_ids")


def test_actions_130_140():
    text = (
        "picking.action_done()\n"
        "self.picking_ids.action_done()\n"
        "payment.post()\n"
        "move.post()\n"
        "order.action_done()\n"
    )
    new = _apply("text_replaces", "migrate_130_140", ".py", text)
    assert new == (
        "picking._action_done()\n"
        "self.picking_ids._action_done()\n"
        "payment.action_post()\n"
        "move.post()\n"
        "order.action_done()\n"
    )
    assert _apply("text_replaces", "migrate_130_140", ".py", new) == new
    warnings = _yaml_rules("text_warnings", "migrate_130_140", ".py")
    assert [line for line in new.splitlines() if _matching(warnings, line)] == []
    assert _matching(warnings, "rec.action_done()")


def test_exceptions_and_invoice_120_130():
    text = (
        "from odoo.exceptions import AccessError, ValidationError, Warning\n"
        "from odoo.exceptions import UserError, Warning\n"
        "from odoo.exceptions import Warning\n"
        "raise Warning(_('x'))\n"
        "warnings.warn('x', Warning)\n"
        "invoice.action_invoice_open()\n"
        "rec.number, rec.type\n"
    )
    new = _apply("text_replaces", "migrate_120_130", ".py", text)
    assert new == (
        "from odoo.exceptions import AccessError, ValidationError, UserError\n"
        "from odoo.exceptions import UserError\n"
        "from odoo.exceptions import UserError\n"
        "raise UserError(_('x'))\n"
        "warnings.warn('x', Warning)\n"
        "invoice.action_post()\n"
        "rec.number, rec.type\n"
    )
    assert _apply("text_replaces", "migrate_120_130", ".py", new) == new
    xml = '<field name="type"/><field name="inherit_id" ref="account.invoice_form"/>'
    assert _apply("text_replaces", "migrate_120_130", ".xml", xml) == (
        '<field name="type"/><field name="inherit_id" ref="account.view_move_form"/>'
    )


def test_invoice_fields_follow_account_move_120_130(tmp_path, caplog):
    import logging

    from odoo_module_migrate.migration_scripts.migrate_120_130 import MigrationScript

    module = tmp_path / "x_mod"
    module.mkdir()
    (module / "__manifest__.py").write_text("{'name': 'x', 'depends': ['account']}")
    (module / "models.py").write_text(
        "from odoo import models\n\n\nclass Invoice(models.Model):\n"
        '    _inherit = "account.move"\n\n    def _x(self):\n'
        "        return self.date_invoice, self.number, self.name\n"
    )
    script = MigrationScript()
    script.parse_rules()
    with caplog.at_level(logging.WARNING):
        script.handle_fields(module)
    text = (module / "models.py").read_text()
    assert "return self.invoice_date, self.name, self.name\n" in text
    # account.move.name is not reported as removed (merged model)
    assert "account.move.name" not in caplog.text


def test_blocked_rules_are_loaded():
    """[model, field, null] rows of curated.yaml block the generated renames."""
    for step, key in (
        ("migrate_130_140", ["stock.move", "date_expected"]),
        ("migrate_130_140", ["crm.lead", "planned_revenue"]),
        ("migrate_160_170", ["hr.expense", "total_amount_company"]),
    ):
        rows = yaml.safe_load(open(f"{SCRIPTS}/renamed_fields/{step}/curated.yaml", encoding="utf-8"))
        assert [r[2] for r in rows if r[:2] == key] == [None], (step, key)


def test_core_api_120_130():
    errors = _yaml_rules("text_errors", "migrate_120_130", ".py")
    assert _matching(errors, "from odoo.osv.orm import setup_modifiers")
    assert _matching(errors, "img = tools.image_resize_image_medium(data)")
    assert not _matching(errors, "img = tools.image_process(data, size=(128, 128))")


def test_model_rename_in_field_text_120_130(tmp_path):
    from odoo_module_migrate.migration_scripts.migrate_120_130 import MigrationScript

    script = MigrationScript()
    script.parse_rules()
    replaces = script.handle_renamed_models(script._RENAMED_MODELS)["replaces"]
    xml = (
        '<field name="model">account.invoice</field>\n'
        '<field name="res_model">account.invoice.line</field>\n'
        '<field name="name">account.invoice</field>\n'
    )
    import re

    for pattern, repl in replaces.items():
        xml = re.sub(pattern, repl, xml)
    assert xml == (
        '<field name="model">account.move</field>\n'
        '<field name="res_model">account.move.line</field>\n'
        '<field name="name">account.invoice</field>\n'
    )


def test_module_rules_110_120():
    rules = _module_rules("migrate_110_120")
    new, messages = manifest.apply_module_rules(
        ["mrp_repair", "product_extended", "website_sale_options", "account_budget", "sale"], rules
    )
    assert new == ["repair", "mrp_bom_cost", "website_sale", "account_budget", "sale"]
    assert all(level == "info" for level, _msg in messages), messages


def test_module_rules_100_110():
    rules = _module_rules("migrate_100_110")
    new, messages = manifest.apply_module_rules(
        ["crm_project_issue", "account_accountant", "stock_picking_wave", "sale"], rules
    )
    assert new == ["crm_project", "account_accountant", "stock_picking_batch", "sale"]
    assert all(level == "info" for level, _msg in messages), messages


def test_rules_110_120():
    errors = _yaml_rules("text_errors", "migrate_110_120", ".py")
    assert _matching(errors, "    'test': ['test/sale_order.yml'],")
    assert not _matching(errors, "    'data': ['views/sale_order.xml'],")
    rows = yaml.safe_load(open(f"{SCRIPTS}/renamed_models/migrate_110_120/curated.yaml", encoding="utf-8"))
    assert ["signature.request", "sign.request"] in [r[:2] for r in rows]


def test_model_rename_keeps_field_names_110_120():
    """product.uom -> uom.uom must not touch the product_uom field."""
    import re

    from odoo_module_migrate.migration_scripts.migrate_110_120 import MigrationScript

    script = MigrationScript()
    script.parse_rules()
    res = script.handle_renamed_models(script._RENAMED_MODELS)
    text = (
        "vals = {'product_uom': uom.id}\n"
        "uom = self.env['product.uom']\n"
        "ref = 'product.model_product_uom'\n"
    )
    for pattern, repl in res["replaces"].items():
        text = re.sub(pattern, repl, text)
    assert text == (
        "vals = {'product_uom': uom.id}\n"
        "uom = self.env['uom.uom']\n"
        "ref = 'product.model_uom_uom'\n"
    )
    assert not any(re.search(p, "vals = {'product_uom': 1}") for p in res["warnings"])


def test_uom_xmlids_110_120():
    text = "self.env.ref('product.product_uom_unit'), ref=\"product.product_uom_categ_kgm\", product.product_uom_unknown"
    rules = _yaml_rules("text_replaces", "migrate_110_120", "*")
    import re

    for pattern, repl in rules.items():
        text = re.sub(pattern, repl, text)
    assert text == "self.env.ref('uom.product_uom_unit'), ref=\"uom.product_uom_categ_kgm\", product.product_uom_unknown"
