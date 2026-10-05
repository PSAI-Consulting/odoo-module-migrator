# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import pytest

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
