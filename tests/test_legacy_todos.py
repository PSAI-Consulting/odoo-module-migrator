import re

from odoo_module_migrate.migration_scripts.migrate_110_120 import MigrationScript


def test_odoo12_view_accessibility_todos_are_reported_by_patterns():
    warnings = MigrationScript()._file_rules(".xml")["warnings"]
    patterns = [(re.compile(pattern), message) for pattern, message in warnings.items()]

    broken = """<odoo><record><field name="arch" type="xml">
    <search><filter string="Open" domain="[]"/></search>
    <tree><button name="run" type="object"/></tree>
    <form><label string="Caption"/></form>
    </field></record></odoo>"""
    assert len([message for pattern, message in patterns if pattern.search(broken)]) == 3

    valid = """<search><filter name="open" string="Open" domain="[]"/></search>
    <tree><button name="run" type="object" string="Run"/></tree>
    <form><label for="name" string="Caption"/></form>"""
    assert not [message for pattern, message in patterns if pattern.search(valid)]
