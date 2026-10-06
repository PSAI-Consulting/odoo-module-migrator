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
        text = re.sub(pattern, repl, text)
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
