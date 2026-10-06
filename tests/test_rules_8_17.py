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
