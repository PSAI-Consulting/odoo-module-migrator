# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
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


def test_resolve_chains():
    rules = [("a", "merged", "b", ""), ("b", "merged", "c", ""), ("d", "removed", None, "")]
    assert ec.resolve_chains(rules) == [
        ("a", "merged", "c", ""), ("b", "merged", "c", ""), ("d", "removed", None, ""),
    ]
