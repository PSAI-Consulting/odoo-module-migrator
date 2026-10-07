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


def test_metadata_extractors(tmp_path, monkeypatch):
    import extract_fields as ef
    import yaml
    from types import SimpleNamespace

    monkeypatch.setattr(ec, "resolve_ref", lambda repo, version: version)
    monkeypatch.setattr(ec, "git", lambda *args: "a" * 40)
    def blobs(repo, ref, pattern):
        if pattern.search("model.py"):
            kind = "Float" if ref == "19.0" else "Integer"
            return {"addons/sale/models/line.py": f"class Line(Model):\n    _name = 'sale.order.line'\n    customer_lead = fields.{kind}()\n"}
        name = "Product Unit of Measure" if ref == "19.0" else "Product Unit"
        return {"addons/uom/data/uom.xml": f'<odoo><record id="precision" model="decimal.precision"><field name="name">{name}</field></record></odoo>'}
    monkeypatch.setattr(ef, "read_blobs", blobs)
    output = tmp_path / "types.yaml"
    args = SimpleNamespace(repo=["odoo"], from_version="19.0", to_version="20.0", output=str(output))
    ec.extract_field_types(args)
    rows = yaml.safe_load(output.read_text())
    assert rows[0][:4] == ["sale.order.line", "customer_lead", "Float", "Integer"]
    assert "addons/sale/models/line.py" in rows[0][4]
    ec.extract_decimal_precisions(args)
    snapshots = yaml.safe_load(output.read_text())
    assert snapshots["from"]["uom.precision"]["name"] == "Product Unit of Measure"
    assert snapshots["to"]["uom.precision"]["name"] == "Product Unit"
