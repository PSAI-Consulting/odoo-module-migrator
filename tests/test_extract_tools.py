# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""tools/extract_changes.py models / js / views and fields --sources, on a
small git repository built by the test."""

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import extract_assets as ea  # noqa: E402
import extract_changes as ec  # noqa: E402
import extract_fields as ef  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _commit(repo, files, message, delete=()):
    for path, text in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for path in delete:
        (repo / path).unlink()
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)


MODEL_V1 = '''from odoo import fields, models


class ResBank(models.Model):
    _name = "res.bank"

    name = fields.Char()
    bic = fields.Char()
    country = fields.Many2one("res.country")


class Old(models.Model):
    _name = "x.old"

    a = fields.Char()
'''

MODEL_V2 = '''from odoo import fields, models


class ResBankInstitution(models.Model):
    _name = "res.bank.institution"

    name = fields.Char()
    bic = fields.Char()
    other = fields.Char()
'''

JS_V1 = {
    "addons/web/__manifest__.py": "{}",
    "addons/web/static/src/core/utils/dates.js":
        "export function parseDate() {}\nexport const FORMAT = 1;\n",
    "addons/web/static/src/core/gone.js": "export class Gone {}\n",
    "addons/mail/__manifest__.py": "{}",
    "addons/mail/static/src/utils/tools.js": "export function tool() {}\n",
}

VIEWS_V1 = '''<odoo>
    <record id="view_form" model="ir.ui.view"><field name="name">f</field></record>
    <record id="view_kept" model="ir.ui.view"><field name="name">k</field></record>
    <template id="tmpl_old"><div/></template>
    <record id="action" model="ir.actions.act_window"><field name="name">a</field></record>
</odoo>
'''


@pytest.fixture()
def repo(tmp_path):
    repo = tmp_path / "odoo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "19.0")
    _commit(repo, {
        "addons/base/__manifest__.py": "{}",
        "addons/base/models/res_bank.py": MODEL_V1,
        "addons/base/views/views.xml": VIEWS_V1,
        **JS_V1,
    }, "init")
    _git(repo, "checkout", "-q", "-b", "20.0")
    _commit(repo, {"addons/base/models/res_bank.py": MODEL_V2}, "[IMP] base: bank institutions")
    _commit(repo, {
        "addons/web/static/src/core/l10n/dates.js":
            "export function parseDate() {}\nexport const FORMAT = 1;\nexport const NEW = 2;\n",
        "addons/web/static/src/utils/tools.js": "export function tool() {}\n",
        "addons/base/views/views.xml": VIEWS_V1.replace(
            '    <record id="view_form" model="ir.ui.view"><field name="name">f</field></record>\n', ""
        ).replace('    <template id="tmpl_old"><div/></template>\n', ""),
    }, "[MOV] web: dates in l10n", delete=[
        "addons/web/static/src/core/utils/dates.js", "addons/web/static/src/core/gone.js",
        "addons/mail/static/src/utils/tools.js",
    ])
    return repo


def _refs(version):
    return lambda repo: version


def test_model_changes(repo):
    removed, candidates = ef.model_changes([repo], _refs("19.0"), _refs("20.0"))
    assert candidates == [("res.bank", "res.bank.institution", "odoo " + candidates[0][2].split()[1]
                           + " '[IMP] base: bank institutions'")]
    assert [r[0] for r in removed] == ["x.old"]
    assert "bank institutions" in removed[0][1]


def test_extract_models_files(repo, tmp_path):
    out = tmp_path / "scripts"
    ec.main(["models", "--from", "19.0", "--to", "20.0", "--repo", str(repo), "--output-dir", str(out)])
    removed = yaml.safe_load((out / "removed_models/migrate_190_200/generated.yaml").read_text())
    assert [r[0] for r in removed] == ["x.old"]
    # rename candidates are commented out: never applied without review
    candidates = (out / "renamed_models/migrate_190_200/candidates.yaml").read_text()
    assert yaml.safe_load(candidates) is None
    assert '# - ["res.bank", "res.bank.institution"' in candidates


def test_js_changes(repo):
    moved, removed = ea.js_changes([repo], _refs("19.0"), _refs("20.0"))
    assert [(m[0], m[1]) for m in moved] == [
        ("@mail/utils/tools", "@web/utils/tools"), ("@web/core/utils/dates", "@web/core/l10n/dates"),
    ]
    assert [(r[0], r[1]) for r in removed] == [("@web/core/gone", "")]


def test_extract_js_rules_apply_once(repo, tmp_path):
    out = tmp_path / "scripts"
    ec.main(["js", "--from", "19.0", "--to", "20.0", "--repo", str(repo), "--output-dir", str(out)])
    replaces = yaml.safe_load((out / "text_replaces/migrate_190_200/js_modules.yaml").read_text())
    errors = yaml.safe_load((out / "text_errors/migrate_190_200/js_modules.yaml").read_text())
    js = ("import { parseDate } from '@web/core/utils/dates';\n"
          'import { Gone } from "@web/core/gone";\n'
          'import { x } from "@web/core/utils/dates_extra";\n')

    def apply(text, ext):
        for pattern, repl in replaces[ext].items():
            text = re.sub(pattern, repl, text)
        return text

    new = apply(js, ".js")
    assert "from '@web/core/l10n/dates';" in new
    assert '"@web/core/utils/dates_extra"' in new  # other module untouched
    assert apply(new, ".js") == new  # idempotent
    assert any(re.search(p, new) for p in errors[".js"])
    # moved to another module: reported, not rewritten (depends to check)
    cross = 'import { tool } from "@mail/utils/tools";\n'
    assert apply(cross, ".js") == cross
    assert any(re.search(p, cross) and "@web/utils/tools" in m for p, m in errors[".js"].items())
    manifest = "'assets': {'web.assets_backend': ['web/static/src/core/utils/dates.js']}"
    assert "web/static/src/core/l10n/dates.js" in apply(manifest, ".py")


def test_view_changes(repo, tmp_path):
    removed = ea.view_changes([repo], _refs("19.0"), _refs("20.0"))
    assert [r[0] for r in removed] == ["base.tmpl_old", "base.view_form"]
    out = tmp_path / "scripts"
    ec.main(["views", "--from", "19.0", "--to", "20.0", "--repo", str(repo), "--output-dir", str(out)])
    errors = yaml.safe_load((out / "text_errors/migrate_190_200/views.yaml").read_text())
    xml = '<field name="inherit_id" ref="base.view_form"/>'
    assert any(re.search(p, xml) for p in errors[".xml"])
    assert not any(re.search(p, '<field name="inherit_id" ref="base.view_kept"/>') for p in errors[".xml"])
    assert not any(re.search(p, '<field name="inherit_id" ref="base.view_form_2"/>') for p in errors[".xml"])
    assert any(re.search(p, "self.env.ref('base.tmpl_old')") for p in errors[".py"])


def test_js_exports():
    text = ("export class A {}\nexport default function b() {}\n"
            "const c = 1; const d = 2;\nexport { c, d as e };\nexport const f = () => 1;\n")
    assert ea.js_exports(text) == {"A", "b", "default", "c", "e", "f"}


def test_merge_changes():
    renamed, removed, candidates = ef.merge_changes(
        ([("m", "a", "b", "ou")], [("m", "x", "ou"), ("m", "c", "ou")]),
        ([("m", "a", "b2", "src"), ("m", "d", "e", "src")],
         [("m", "x", "src"), ("m", "y", "src"), ("m", "d", "src")],
         [("m", "c", "c2", "src"), ("m", "a", "z", "src")]),
    )
    assert renamed == [("m", "a", "b", "ou"), ("m", "d", "e", "src")]
    assert candidates == [("m", "c", "c2", "src")]
    assert removed == [("m", "x", "ou"), ("m", "y", "src")]


NEW_SYNTAX = '''from odoo import fields, models


class MrpBom(models.Model):
    _name = 'mrp.bom'
    _inherit = ['mail.thread', 'product.catalog.mixin']
    _inherits = {'product.template': 'product_tmpl_id'}

    code = fields.Char()

    def _check(self, errors):
        return f"{', '.join(errors)}"


class Partner(models.Model):
    _inherit = "res.partner"
'''


def test_regex_fallback_for_newer_syntax():
    """Files that the running Python cannot parse (Odoo 20 f-strings with
    3.11) are still read: models and their parents are not lost."""
    files = {"addons/mrp/models/mrp_bom.py": NEW_SYNTAX}
    assert ef.defined_models(files) == {"mrp.bom": "addons/mrp/models/mrp_bom.py"}
    assert ef._regex_classes(NEW_SYNTAX) == [
        ("mrp.bom", ["mail.thread", "product.catalog.mixin", "product.template"]),
        (None, ["res.partner"]),
    ]
    parents = ef.model_parents(files)
    assert parents["mrp.bom"] == {"mail.thread", "product.catalog.mixin", "product.template"}


def test_ground_truth_similarity(tmp_path):
    import ground_truth as gt

    def module(name, text):
        path = tmp_path / name / "m"
        (path / "views").mkdir(parents=True)
        (path / "views" / "v.xml").write_text(text)
        (path / "i18n").mkdir()
        (path / "i18n" / "fr.po").write_text("ignored")
        return path

    original = module("o", "<tree>\n<field name='a'/>\n\n<field name='b'/>\n</tree>\n")
    migrated = module("m", "<list>\n<field name='a'/>\n<field name='b'/>\n</list>\n")
    expected = module("e", "<list>\n<field name='a'/>\n<field name='c'/>\n</list>\n")
    assert gt.similarity(original, expected) == (1, 4)
    assert gt.similarity(migrated, expected) == (3, 4)
    assert gt.missed(original, migrated, expected) == {"<field name='b'/>": 1}


def test_log_range_history_ref(repo):
    """With a local full-history branch, searches stop at its lineage."""
    import subprocess as sp

    head = lambda ref: sp.run(["git", "-C", str(repo), "rev-parse", ref], capture_output=True, text=True).stdout.strip()
    assert ef.log_range(repo, "19.0", "20.0") == "19.0..20.0"
    ef.HISTORY_REF = "20.0"
    try:
        ef._RANGES.clear()
        assert ef.log_range(repo, "19.0", "20.0") == f"{head('19.0')}..{head('20.0')}"
    finally:
        ef.HISTORY_REF = None
        ef._RANGES.clear()


def test_openupgrade_old_layout(tmp_path):
    """OpenUpgrade 13.0 and before is a fork of Odoo: apriori.py and the
    analyses live in openupgrade_records / addons/*/migrations/."""
    ou = tmp_path / "ou"
    ou.mkdir()
    _git(ou, "init", "-q", "-b", "13.0")
    _commit(ou, {
        "odoo/addons/openupgrade_records/lib/apriori.py":
            "renamed_modules = {'web_settings_dashboard': 'base_setup'}\nmerged_modules = {'account_cancel': 'account', 'gift_card ': 'loyalty'}\n",
        "addons/sale/migrations/13.0.1.1/openupgrade_analysis.txt":
            "sale         / sale.order               / x_old (char)                  : DEL \n"
            "obsolete model sale.old\n",
        "addons/sale/migrations/13.0.1.1/pre-migration.py":
            "_field_renames = [('sale.order', 'sale_order', 'a', 'b')]\n",
    }, "init")
    renamed, merged = ec.load_apriori(str(ou), "13.0")
    assert renamed == {"web_settings_dashboard": "base_setup"}
    # stray space stripped ("gift_card " in OpenUpgrade 16.0)
    assert merged == {"account_cancel": "account", "gift_card": "loyalty"}
    ren, ren_models, removed, removed_models = ef.openupgrade_changes(ou, "13.0", lambda m: True)
    assert [r[:3] for r in ren] == [("sale.order", "a", "b")]
    assert [r[:2] for r in removed] == [("sale.order", "x_old")]
    assert [r[0] for r in removed_models] == ["sale.old"]


def test_openupgrade_rename_variable_names(tmp_path):
    """OpenUpgrade 16.0 / 17.0 also name the lists _fields_renames and
    _models_renames (loyalty: coupon.program -> loyalty.program)."""
    ou = tmp_path / "ou"
    ou.mkdir()
    _git(ou, "init", "-q", "-b", "16.0")
    _commit(ou, {
        "openupgrade_scripts/scripts/loyalty/16.0.1.0/pre-migration.py":
            "_fields_renames = [('coupon.program ', 'coupon_program', 'a', 'b')]\n"
            "_models_renames = [('coupon.program', 'loyalty.program')]\n"
            "_field_renames_event_sale = [('event.event', 'event_event', 'c', 'd')]\n"
            "_column_renames = {'x': [('e', 'f')]}\n",
    }, "init")
    ren, ren_models, _removed, _removed_models = ef.openupgrade_changes(ou, "16.0", lambda m: True)
    assert sorted(r[:3] for r in ren) == [("coupon.program", "a", "b"), ("event.event", "c", "d")]
    assert [r[:2] for r in ren_models] == [("coupon.program", "loyalty.program")]


def test_openupgrade_rename_of_a_field_still_defined(repo, tmp_path):
    """OpenUpgrade renames a column whose old field still exists in the target
    (16.0 mrp.workcenter capacity -> default_capacity): candidate only."""
    ou = tmp_path / "ou"
    ou.mkdir()
    _git(ou, "init", "-q", "-b", "20.0")
    _commit(ou, {
        "openupgrade_scripts/scripts/base/20.0.1.0/pre-migration.py":
            "_field_renames = [\n"
            "    ('res.bank.institution', 'res_bank_institution', 'bic', 'swift'),\n"
            "    ('res.bank.institution', 'res_bank_institution', 'old_other', 'other'),\n"
            "]\n",
    }, "init")
    out = tmp_path / "scripts"
    ec.main(["fields", "--from", "19.0", "--to", "20.0", "--repo", str(repo), "--models", "res.",
             "--openupgrade", str(ou), "--output-dir", str(out)])
    generated = yaml.safe_load((out / "renamed_fields/migrate_190_200/generated.yaml").read_text())
    assert [r[:3] for r in generated] == [["res.bank.institution", "old_other", "other"]]
    candidates = (out / "renamed_fields/migrate_190_200/candidates.yaml").read_text()
    assert '# - ["res.bank.institution", "bic", "swift"' in candidates
    assert "old field still defined in 20.0" in candidates


def test_oldname_renames(tmp_path):
    """Odoo <= 12.0 declares renames with oldname= (11.0 delivery.carrier:
    free_over = fields.Boolean(..., oldname='free_if_more_than'))."""
    repo = tmp_path / "odoo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "10.0")
    v10 = (
        "from odoo import fields, models\n\n\nclass Carrier(models.Model):\n"
        "    _name = 'delivery.carrier'\n\n"
        "    free_if_more_than = fields.Boolean()\n    old_kept = fields.Char()\n"
    )
    _commit(repo, {"addons/delivery/models/carrier.py": v10}, "init")
    _git(repo, "checkout", "-q", "-b", "11.0")
    v11 = (
        "from odoo import fields, models\n\n\nclass Carrier(models.Model):\n"
        "    _name = 'delivery.carrier'\n\n"
        "    free_over = fields.Boolean(oldname='free_if_more_than')\n"
        "    old_kept = fields.Char()\n    other = fields.Char(oldname='old_kept')\n"
        "    ancient = fields.Char(oldname='never_in_10')\n"
    )
    _commit(repo, {"addons/delivery/models/carrier.py": v11}, "rename")
    renames = ef.oldname_renames([repo], _refs("10.0"), _refs("11.0"), lambda m: True)
    # old_kept still exists, never_in_10 did not exist in 10.0: not renames
    assert [r[:3] for r in renames] == [("delivery.carrier", "free_if_more_than", "free_over")]
    assert "oldname='free_if_more_than'" in renames[0][3]


def test_api_module_name_openerp():
    """9.0 has openerp/, 10.0 odoo/: both are named odoo.* to be compared."""
    import extract_api

    assert extract_api._module_name("openerp/tools/misc.py") == "odoo.tools.misc"
    assert extract_api._module_name("odoo/tools/misc.py") == "odoo.tools.misc"
    assert extract_api._module_name("openerp/addons/base/res/res_partner.py") is None
