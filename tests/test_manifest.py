# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import pytest
import logging

from odoo_module_migrate import manifest as m

RULES = [
    ["stock_picking_batch", "merged", "stock"],
    ["web_editor", "merged", "html_editor"],
    ["account_peppol_response", "removed"],
]


def _apply(text):
    depends, messages = m.apply_module_rules(m.get_depends(text), RULES)
    return m.rewrite_depends(text, depends), messages


def test_multiline_layout_kept():
    text = """{
    'name': "Société",
    'depends': [
        "stock",
        'stock_picking_batch',
        'web_editor',
    ],
    'data': ['views/stock_picking_batch.xml'],
}
"""
    new, _ = _apply(text)
    assert new == """{
    'name': "Société",
    'depends': [
        "stock",
        'html_editor',
    ],
    'data': ['views/stock_picking_batch.xml'],
}
"""


def test_one_line_layout_kept():
    new, _ = _apply("{'name': 'é', 'depends': ['web_editor', 'sale']}")
    assert new == "{'name': 'é', 'depends': ['html_editor', 'sale']}"


def test_removed_module_kept_and_reported():
    text = "{'depends': ['account_peppol_response']}"
    new, messages = _apply(text)
    assert new == text
    assert messages[0][0] == "error"


def test_idempotent():
    text = "{'depends': [\n    'stock_picking_batch',\n    'stock',\n]}"
    once, _ = _apply(text)
    twice, messages = _apply(once)
    assert once == twice == "{'depends': [\n    'stock',\n]}"
    assert not messages


def test_leading_indentation_accepted():
    # accepted by Odoo (ast.literal_eval strips it)
    text = "  {'name': 'x', 'depends': ['web_editor']}\n"
    new, _ = _apply(text)
    assert new == "  {'name': 'x', 'depends': ['html_editor']}\n"


def test_comments_are_not_rewritten():
    with pytest.raises(m.ManifestError):
        m.rewrite_depends("{'depends': [\n  'a',  # comment\n]}", ["b"])


def test_bump_version_formats():
    from odoo_module_migrate.migration_scripts.python_scripts.migrate_allways.smart_bump_version import (
        _adapt_version_format as bump,
    )

    assert bump("17.0", "20.0") == "20.0.1.0.0"  # '20.0' alone is refused by Odoo 20
    assert bump("17.0.1.0.0", "20.0") == "20.0.1.0.0"
    assert bump("20.0.1.0.0", "20.0") == "20.0.1.0.0"
    assert bump("17.0.1", "20.0") == "20.0.1"
    assert bump("0.1", "20.0") == "20.0.0.1"


def test_missing_version_is_inserted_and_concatenated_key_is_reported(tmp_path, caplog):
    from odoo_module_migrate import quality, tools
    from odoo_module_migrate.migration_scripts.python_scripts.migrate_allways.smart_bump_version import (
        bump_revision,
    )

    path = tmp_path / "__manifest__.py"
    path.write_text("{'name': 'X', 'category': 'Contact', 'Sales' 'version': '0.1'}")
    unknown, concatenated = m.inspect_keys(path.read_text())
    assert unknown == [("Salesversion", 1)]
    assert concatenated == [("Salesversion", 1)]
    caplog.set_level(logging.ERROR)
    quality.finish_module(tmp_path, cosmetic=False)
    assert "adjacent string literals" in caplog.text
    assert caplog.text.count("Salesversion") == 1

    bump_revision(
        tools=tools,
        manifest_path=path,
        migration_steps=[{"target_version_name": "20.0"}],
        logger=logging.getLogger("test"),
    )

    data = eval(path.read_text(), {"__builtins__": {}})  # noqa: S307 - literal fixture
    assert data["version"] == "20.0.1.0.0"
    assert data["Salesversion"] == "0.1"
