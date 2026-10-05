# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo_module_migrate.upgrade_code.prepare import move_access_records

MANIFEST = """{
    'name': 'x',
    'data': [
        'security/security.xml',
        'views/config_views.xml',
        'views/menu.xml',
    ],
}
"""
VIEWS = """<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_x" model="ir.ui.view">
        <field name="name">x</field>
    </record>
    <record id="x_rule" model="ir.rule">
        <field name="name">Rule</field>
        <field name="domain_force">[('company_id', 'in', company_ids)]</field>
    </record>
</odoo>
"""


def test_move_access_records(tmp_path):
    module = tmp_path / "x_module"
    (module / "views").mkdir(parents=True)
    (module / "security").mkdir()
    (module / "__manifest__.py").write_text(MANIFEST, encoding="utf-8")
    (module / "security" / "security.xml").write_text("<odoo/>\n", encoding="utf-8")
    (module / "views" / "config_views.xml").write_text(VIEWS, encoding="utf-8")
    (module / "views" / "menu.xml").write_text("<odoo/>\n", encoding="utf-8")

    assert move_access_records(module) == ["views/config_views.xml"]
    views = (module / "views" / "config_views.xml").read_text(encoding="utf-8")
    moved = (module / "security" / "x_module_access_moved.xml").read_text(encoding="utf-8")
    manifest = (module / "__manifest__.py").read_text(encoding="utf-8")
    assert "ir.rule" not in views and "view_x" in views
    assert 'id="x_rule" model="ir.rule"' in moved
    assert manifest.index("security/x_module_access_moved.xml") < manifest.index("views/config_views.xml")
    assert "        'security/x_module_access_moved.xml',\n        'views/config_views.xml'," in manifest
    # second run: nothing left to move
    assert move_access_records(module) == []
