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


def test_access_records_left_reported_after_conversion(tmp_path):
    """19.0 -> 20.0: only the access records still there once converted are
    reported (they were all reported before the conversion), each report
    gets its own 'Running migration' line."""
    from odoo_module_migrate.__main__ import main

    for name in ("a_module", "b_module"):
        module = tmp_path / name
        (module / "security").mkdir(parents=True)
        (module / "__manifest__.py").write_text(
            "{'name': 'x', 'version': '19.0.1.0.0', 'depends': ['base'],"
            " 'data': ['security/ir.model.access.csv', 'security/rules.xml', 'security/override.xml']}",
            encoding="utf-8",
        )
        (module / "security" / "ir.model.access.csv").write_text(
            "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
            "access_x,x,model_x,base.group_user,1,1,1,1\n", encoding="utf-8")
        (module / "security" / "rules.xml").write_text(
            '<odoo>\n    <!-- <function model="ir.rule" name="write"/> -->\n'
            '    <record id="x_rule" model="ir.rule">\n'
            '        <field name="model_id" ref="model_x"/>\n'
            '        <field name="groups" eval="[(4, ref(\'base.group_user\'))]"/>\n'
            "        <field name=\"domain_force\">[('user_id', '=', user.id)]</field>\n"
            "    </record>\n</odoo>\n", encoding="utf-8")
        (module / "security" / "override.xml").write_text(
            '<odoo>\n\n    <function model="ir.rule" name="write">\n'
            "        <value eval=\"ref('base.res_partner_rule')\"/>\n"
            "        <value eval=\"{'active': False}\"/>\n    </function>\n</odoo>\n",
            encoding="utf-8")
    (tmp_path / "b_module" / "unused.xml").write_text('<odoo><record id="r" model="ir.rule"/></odoo>')
    main([
        "--directory", str(tmp_path), "--modules", "a_module,b_module",
        "--init-version-name", "19.0", "--target-version-name", "20.0",
        "--no-commit", "--no-pre-commit", "--log-level", "INFO",
        "--report-dir", str(tmp_path / "reports"),
    ])
    for name in ("a_module", "b_module"):
        assert 'id="x_rule"' not in (tmp_path / name / "security" / "rules.xml").read_text(encoding="utf-8")
        text = (tmp_path / "reports" / f"{name}.md").read_text(encoding="utf-8")
        left = [line for line in text.splitlines() if "record left in XML" in line]
        assert len(left) == 1 and "security/override.xml:3" in left[0], left
        assert "Running migration" not in text
        assert "The model ir.rule has been deprecated" not in text
