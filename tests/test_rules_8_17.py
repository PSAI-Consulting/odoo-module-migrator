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
