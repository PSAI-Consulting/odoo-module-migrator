# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo_module_migrate.analysis.fields import apply_renames, python_usages, xml_usages

PY = '''from odoo import api, fields, models


class ResGroups(models.Model):
    _inherit = "res.groups"

    user_count = fields.Integer(compute="_compute_user_count")
    first_user = fields.Many2one(related="users.partner_id")

    @api.depends("users", "users.active")
    def _compute_user_count(self):
        for group in self:
            group.user_count = len(group.users)
        self.write({"users": [(5,)]})
        partners = self.env["res.partner"].search([("mobile", "!=", False)])
        users = self.users


class Other(models.Model):
    _name = "x.other"

    def f(self):
        return self.users  # another model: not res.groups
'''


def _keys(usages):
    return sorted({(u.model, u.field, u.line) for u in usages})


def test_python_usages_only_known_models():
    usages, defined = python_usages(PY)
    keys = _keys(usages)
    assert ("res.groups", "users", 8) in keys          # related=
    assert ("res.groups", "users", 10) in keys         # @api.depends
    assert ("res.groups", "users", 13) in keys         # group.users (for group in self)
    assert ("res.groups", "users", 14) in keys         # self.write({...})
    assert ("res.partner", "mobile", 15) in keys       # self.env[...].search
    assert ("res.groups", "users", 16) in keys
    assert ("x.other", "users", 23) in keys            # own model, reported as x.other
    assert not [k for k in keys if k[1] == "write"]    # methods are not fields
    assert defined["res.groups"] == {"user_count", "first_user"}


def test_python_renames():
    usages, _ = python_usages(PY)
    new, count = apply_renames(PY, usages, {("res.groups", "users"): "user_ids"})
    assert count == 6
    assert 'related="user_ids.partner_id"' in new
    assert '@api.depends("user_ids", "user_ids.active")' in new
    assert "len(group.user_ids)" in new
    assert 'self.write({"user_ids": [(5,)]})' in new
    assert "return self.users  # another model" in new
    # idempotent
    again, count = apply_renames(new, python_usages(new)[0], {("res.groups", "users"): "user_ids"})
    assert (again, count) == (new, 0)


XML = '''<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="group_manager" model="res.groups">
        <field name="name">Manager</field>
        <field name="users" eval="[(4, ref('base.user_admin'))]"/>
    </record>
    <record id="view_partner_form" model="ir.ui.view">
        <field name="model">res.partner</field>
        <field name="inherit_id" ref="base.view_partner_form"/>
        <field name="arch" type="xml">
            <xpath expr="//field[@name='mobile']" position="after">
                <field name="phone"/><field name="mobile"/>
            </xpath>
            <field name="child_ids">
                <list><field name="mobile"/></list>
            </field>
        </field>
    </record>
</odoo>
'''


def test_xml_usages():
    keys = _keys(xml_usages(XML))
    assert ("res.groups", "users", 5) in keys
    assert ("res.partner", "mobile", 11) in keys      # xpath
    assert ("res.partner", "mobile", 12) in keys      # second field on the line
    assert ("res.partner", "mobile", 15) not in keys  # sub-view of child_ids


def test_remove_displayed_fields():
    from odoo_module_migrate.analysis.fields import remove_displayed_fields

    new, done = remove_displayed_fields(XML, xml_usages(XML), {("res.partner", "mobile"): ""})
    # the displayed field is removed, the xpath anchor and the sub-view are kept
    assert [u.line for u in done] == [12]
    assert '<field name="phone"/>\n' in new
    assert "//field[@name='mobile']" in new
    assert '<list><field name="mobile"/></list>' in new
    assert remove_displayed_fields(new, xml_usages(new), {("res.partner", "mobile"): ""})[1] == []


def test_xml_multiline_tags():
    xml = '''<odoo>
    <record id="g1" model="res.groups">
        <field
            name="users"
            eval="[(4, ref('base.user_root'))]"
        />
    </record>
    <record id="g2" model="res.groups">
        <field name="users" eval="[(4, ref('base.user_admin'))]"/>
    </record>
</odoo>
'''
    new, count = apply_renames(xml, xml_usages(xml), {("res.groups", "users"): "user_ids"})
    assert count == 2
    assert 'name="users"' not in new
    assert new.count('name="user_ids"') == 2


def test_xml_renames():
    new, count = apply_renames(XML, xml_usages(XML), {("res.groups", "users"): "user_ids"})
    assert count == 1
    assert '<field name="user_ids" eval=' in new
