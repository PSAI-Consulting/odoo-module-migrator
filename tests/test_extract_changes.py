# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "extract"))
import extract_changes as ec  # noqa: E402

AFTER = {"hr", "iot", "website_sale_collect", "esg_hr_fleet", "stock"}


@pytest.mark.parametrize("module,subject,expected", [
    ("hr_hourly_cost", "[REM] hr_hourly_cost: merge module in hr", "hr"),
    ("iot_base", "[REM] iot_base: merge iot_base with iot", "iot"),
    ("website_sale_collect_wishlist",
     "[MOV] website_sale_collect(_wishlist->{}): merge wishlist into base module",
     "website_sale_collect"),
    ("esg_csrd_hr_fleet",
     "[MOV] esg_hr_fleet: move esg_csrd_hr_fleet module to esg_hr_fleet module",
     "esg_hr_fleet"),
    ("transifex", "[REM] transifex: remove outdated module", None),
])
def test_target_from_subject(module, subject, expected):
    assert ec.target_from_subject(subject, module, AFTER) == expected


def test_promote_candidates():
    import extract_fields as ef

    confirmed, rest = ef.promote_candidates([
        ("product.template", "expense_policy", "reinvoice_policy",
         "odoo 8a5b99545dfa '[CLN] sale: rename `expense_policy` field to `reinvoice_policy`'"),
        ("sale.order", "has_rented_products", "has_rentable_lines",
         "enterprise 7cdfe5bd154 '[IMP] sale_renting: switch between SO and RO'"),
        ("res.partner", "x", "y", "odoo abc '[REF] rename stuff'"),  # old name not cited
    ])
    assert [c[1] for c in confirmed] == ["expense_policy"]
    assert [r[1] for r in rest] == ["has_rented_products", "x"]


def test_resolve_chains():
    rules = [("a", "merged", "b", ""), ("b", "merged", "c", ""), ("d", "removed", None, "")]
    assert ec.resolve_chains(rules) == [
        ("a", "merged", "c", ""), ("b", "merged", "c", ""), ("d", "removed", None, ""),
    ]
