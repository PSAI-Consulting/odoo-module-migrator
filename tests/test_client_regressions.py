"""Generic reproductions of migration failures observed on real addons."""

import ast
import logging

from odoo_module_migrate import quality, tools
from odoo_module_migrate.analysis import models, python_checks, views
from odoo_module_migrate.migration import Migration
from odoo_module_migrate.migration_scripts.python_scripts.migrate_180_190.compatibility import (
    migrate_compatibility,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_190_200.view_anchors import (
    migrate_view_anchors,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_170_180.invisible_fields import (
    check_invisible_fields,
)
from odoo_module_migrate.migration_scripts.python_scripts.migrate_170_180.product_storable import (
    migrate_product_storable,
)
from odoo_module_migrate.report import Entry, ModuleReport


def addon(root, name, depends=(), code="", xml="", data=None):
    path = root / name
    path.mkdir(parents=True)
    (path / "__manifest__.py").write_text(
        repr(dict(name=name, depends=list(depends), data=data or ["view.xml"])),
        encoding="utf-8",
    )
    (path / "models.py").write_text(code, encoding="utf-8")
    (path / "view.xml").write_text("<odoo>" + xml + "</odoo>", encoding="utf-8")
    return path


def view(name, arch, parent=None):
    inherit = f'<field name="inherit_id" ref="{parent}"/>' if parent else ""
    return f'<record id="{name}" model="ir.ui.view">{inherit}<field name="arch" type="xml">{arch}</field></record>'


def test_dependency_reads_writes_relations_and_cycles(tmp_path):
    addon(tmp_path, "base", code="class P(Model):\n    _name = 'res.partner'\n")
    addon(
        tmp_path,
        "provider",
        ["consumer"],
        "class P(Model):\n    _inherit = 'res.partner'\n    custom_code = fields.Char()\nclass C(Model):\n    _name = 'custom.category'\n",
    )
    mod = addon(
        tmp_path,
        "consumer",
        ["base"],
        """class P(Model):
    _inherit = 'res.partner'
    partner_id = fields.Many2one('res.partner')
    def run(self):
        for record in self:
            record.partner_id.custom_code = 'x'
        self.env['res.partner'].write({'custom_code': 'y'})
        self.env['custom.category'].search([])
        other = self.env['res.partner'].browse(1)
        return other.custom_code
""",
    )
    index = models.ModelIndex.build([tmp_path, tmp_path])
    issues = list(python_checks.check_module(mod, index))
    assert len(issues) == 4, issues
    assert all(
        "circular dependency" in message and "provider" in message
        for _, _, _, message in issues
    )
    assert all(level == "error" for _, _, level, _ in issues)
    # A missing dependency should lower certainty, not abandon the analysis.
    index.depends["consumer"].append("unavailable")
    assert all(
        level == "warning" for _, _, level, _ in python_checks.check_module(mod, index)
    )


def test_callbacks_inherited_methods_override_and_precision(tmp_path):
    addon(
        tmp_path,
        "base",
        code="""class P(Model):
    _name = 'res.partner'
    def _compute_name(self): pass
    def _search_qty(self, operator, value): pass
""",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["base"],
        """class P(Model):
    _inherit = 'res.partner'
    name = fields.Char(compute='_compute_name')
    qty = fields.Float(search='_search_missing', digits='Missing precision')
    def _search_qty(self, operator, value):
        return []
""",
    )
    issues = list(
        python_checks.check_module(
            mod, models.ModelIndex.build([tmp_path]), precision_names={"Product Unit"}
        )
    )
    messages = [i[-1] for i in issues]
    assert len(messages) == 3, messages
    assert any("_search_missing" in m for m in messages)
    assert any("accidental override" in m for m in messages)
    assert any("decimal precision" in m for m in messages)
    assert not any("_compute_name" in m for m in messages)


def test_unicode_semantics_and_raw_strings():
    text = r"""a = "d\u00e9j\u00e0"
b = r"\u00e9"
c = "\\u00e9"
d = "\u0022"
e = b"\u00e9"
f = "\ud800"
# \u00e9
"""
    new = quality.readable_strings(text)
    assert '"déjà"' in new
    assert ast.dump(ast.parse(text)) == ast.dump(ast.parse(new))
    assert quality.readable_strings(new) == new
    assert "# \\u00e9" in new


def test_quality_and_manifest_access_order(tmp_path, caplog):
    mod = addon(
        tmp_path,
        "custom",
        code="\n\nclass P(Model):\n    _name = 'x.model'\n    def _compute_x(self):\n        self.write({'x': 1})\n        return _(f'Hello {self.id}')\n",
        data=["view.xml", "security/ir.access.csv"],
    )
    (mod / "l10n").mkdir()
    (mod / "l10n/fr.po").write_text("", encoding="utf-8")
    with caplog.at_level(logging.INFO, logger="odoo_module_migrate"):
        quality.finish_module(
            mod, original_data=["security/ir.model.access.csv", "view.xml"]
        )
    manifest = ast.literal_eval((mod / "__manifest__.py").read_text())
    assert manifest["data"] == ["security/ir.access.csv", "view.xml"]
    assert manifest["license"] == "LGPL-3"
    assert not (mod / "models.py").read_text().startswith("\n")
    for fragment in ("F821", "INT001", "_description", "write()", "outside i18n"):
        assert fragment in caplog.text
    before = tools.hash_tree(mod)
    quality.finish_module(mod)
    assert tools.hash_tree(mod) == before


def test_oca_cosmetics_are_preserved(tmp_path):
    mod = addon(tmp_path, "oca", code='\nname = "caf\\u00e9"\n')
    before = tools.hash_tree(mod)
    quality.finish_module(mod, cosmetic=False)
    assert tools.hash_tree(mod) == before


def test_19_rewrites_are_scoped_and_idempotent(tmp_path, caplog):
    mod = addon(
        tmp_path,
        "custom",
        code="""# self._context
LABEL = "Product Unit of Measure self._context"
class P(Model):
    _inherit = 'res.partner'
    qty = fields.Float(digits = 'Product Unit of Measure')
    def run(self):
        self.env.ref('uom.uom_categ_length')
        return self._context, self._cr, self._uid
""",
    )
    args = dict(
        module_path=mod, tools=tools, logger=logging.getLogger("odoo_module_migrate")
    )
    migrate_compatibility(**args)
    text = (mod / "models.py").read_text()
    assert "digits = 'Product Unit'" in text
    assert "return self.env.context, self.env.cr, self.env.uid" in text
    assert (
        "# self._context" in text and '"Product Unit of Measure self._context"' in text
    )
    assert "categories removed" in caplog.text
    migrate_compatibility(**args)
    assert (mod / "models.py").read_text() == text


def test_exact_xpath_and_targeted_repair(tmp_path):
    addon(tmp_path, "base")
    addon(
        tmp_path,
        "sale",
        ["base"],
        xml=view(
            "view_order_form",
            '<form><field name="order_line"><list><column name="price_unit"><field name="price_unit"/></column></list></field></form>',
        ),
    )
    expression = "//form/field[@name='order_line']/list[1]/field[@name='price_unit']"
    mod = addon(
        tmp_path,
        "custom",
        ["sale"],
        xml=view(
            "custom_form",
            f'<xpath expr="{expression}" position="before"><field name="x"/></xpath>',
            "sale.view_order_form",
        ),
    )
    index = views.ViewIndex.build([tmp_path])
    issues = list(views.check_module(mod, index, {"base", "sale"}))
    assert len(issues) == 1 and "Exact selector" in issues[0][-1]
    args = dict(
        module_path=mod, tools=tools, logger=logging.getLogger("odoo_module_migrate")
    )
    migrate_view_anchors(**args)
    assert not list(
        views.check_module(mod, views.ViewIndex.build([tmp_path]), {"base", "sale"})
    )
    text = (mod / "view.xml").read_text()
    migrate_view_anchors(**args)
    assert (mod / "view.xml").read_text() == text


def test_product_header_anchor_moves_before_sheet(tmp_path):
    mod = addon(
        tmp_path,
        "custom",
        xml=view(
            "form",
            '<header position="before"><div class="alert">Review</div></header>',
            "product.product_normal_form_view",
        ),
    )
    args = dict(
        module_path=mod, tools=tools, logger=logging.getLogger("odoo_module_migrate")
    )
    migrate_view_anchors(**args)
    text = (mod / "view.xml").read_text()
    assert '<sheet position="before"><div class="alert">Review</div></sheet>' in text
    migrate_view_anchors(**args)
    assert (mod / "view.xml").read_text() == text


def test_unknown_dependency_and_risk(tmp_path):
    addon(tmp_path, "base", xml=view("form", "<form><group/></form>"))
    mod = addon(
        tmp_path,
        "custom",
        ["base", "missing"],
        xml=view(
            "form",
            '<xpath expr="//group[@expand=\'0\']" position="inside"/>',
            "base.form",
        ),
    )
    issues = list(views.check_module(mod, views.ViewIndex.build([tmp_path]), {"base"}))
    assert issues and "incomplete dependencies" in issues[0][-1]
    report = ModuleReport(
        "custom", mod, [Entry("WARNING", "[incomplete] missing dependency")]
    )
    assert report.risk == "inconnu"


def test_cache_invalidates_and_context_is_deduplicated(tmp_path):
    mod = addon(
        tmp_path,
        "base",
        code="class P(Model):\n    _name = 'res.partner'\n    a = fields.Char()\n",
    )
    assert list(views._module_dirs([tmp_path, tmp_path])) == [mod]
    assert "a" in models.ModelIndex.build([tmp_path]).fields["res.partner"]
    (mod / "models.py").write_text(
        "class P(Model):\n    _name = 'res.partner'\n    b = fields.Char()\n"
    )
    index = models.ModelIndex.build([tmp_path])
    assert "b" in index.fields["res.partner"] and "a" not in index.fields["res.partner"]


def test_invisible_notice_only_for_used_fields(tmp_path, caplog):
    mod = addon(
        tmp_path,
        "custom",
        xml=view(
            "form",
            '<form><field name="used" invisible="1"/><field name="unused" invisible="1"/><field name="name" readonly="used"/></form>',
        ),
    )
    check_invisible_fields(
        module_path=mod, tools=tools, logger=logging.getLogger("odoo_module_migrate")
    )
    assert "Invisible field used" in caplog.text
    assert "Invisible field unused" not in caplog.text


def test_small_migration_end_to_end(tmp_path):
    mod = addon(
        tmp_path,
        "custom",
        ["base"],
        "from odoo import fields, models\nclass P(models.Model):\n    _inherit = 'res.partner'\n    qty = fields.Float(digits='Product Unit of Measure')\n",
    )
    migration = Migration(
        tmp_path, "18.0", "19.0", ["custom"], commit_enabled=False, pre_commit=False
    )
    migration.run()
    assert "digits='Product Unit'" in (mod / "models.py").read_text()
    assert (mod / "MIGRATION_REPORT.md").exists()


def test_formatter_only_changed_non_oca_files(tmp_path, monkeypatch):
    from types import SimpleNamespace

    mod = addon(tmp_path, "custom", code="import os\n")
    (mod / "__init__.py").write_text("from . import models\n")
    (mod / "untouched.py").write_text("import sys\n")
    (tmp_path / ".ruff.toml").write_text("line-length = 99\n")
    migration = Migration(
        tmp_path,
        "18.0",
        "19.0",
        ["custom"],
        commit_enabled=False,
        pre_commit=False,
        format_code=True,
    )
    item = migration._module_migrations[0]
    item._hashes_before = tools.hash_tree(mod)
    (mod / "models.py").write_text("import os\nx=1\n")
    (mod / "__init__.py").write_text("from . import models\n\n")
    commands = []
    monkeypatch.setattr("shutil.which", lambda name: "ruff")
    monkeypatch.setattr(
        "subprocess.run",
        lambda command, **kw: commands.append(command) or SimpleNamespace(returncode=0),
    )
    migration._format_changed_files()
    assert len(commands) == 1
    assert all("untouched.py" not in " ".join(command) for command in commands)
    assert all(str(tmp_path / ".ruff.toml") in command for command in commands)
    assert not any(
        "check" in command and command[-1].endswith("__init__.py")
        for command in commands
    )


def test_manifest_template_preserves_customer_values_and_load_order():
    from odoo_module_migrate.manifest import format_manifest

    original = """# Copyright Example
{
    # business ordering matters
    'data': ['data/first.xml', 'security/ir.access.csv', 'views/form.xml'],
    'author': 'Another Customer',
    'name': 'Café',
    'version': '20.0.1.2.3',
    'description': '',
    'installable': True,
    'auto_install': ['sale'],
    'application': False,
    'custom_key': {'a': True},
}
"""
    result = format_manifest(original, default_website="https://example.test")
    data = ast.literal_eval(result)
    assert data["author"] == "Another Customer"
    assert data["data"] == ast.literal_eval(original)["data"]
    assert data["auto_install"] == ["sale"]
    assert data["license"] == "LGPL-3"
    assert data["website"] == "https://example.test"
    assert "installable" not in data and "description" not in data
    assert "# Copyright Example" in result and "# business ordering matters" in result
    assert format_manifest(result) == result


def test_manifest_scaffold_comments_removed_business_comments_preserved():
    from odoo_module_migrate.manifest import format_manifest

    original = """# -*- coding: utf-8 -*-
{
    'name': 'Composition',
    # Categories can be used to filter modules in modules listing
    # for the full list
    'category': 'base',
    # Explanation specific to this module
    'depends': ['base', 'product'],  # Keep this inline note
    # always loaded
    'data': ['views/product.xml'],
}
"""
    result = format_manifest(original)
    assert "Categories can be used" not in result
    assert "for the full list" not in result
    assert "always loaded" not in result
    assert "# Explanation specific to this module" in result
    assert "# Keep this inline note" in result
    assert result.index("# Explanation specific") < result.index('"depends"')
    assert result.index("# Keep this inline") < result.index('"depends"')
    assert format_manifest(result) == result


def test_manifest_multiline_description_and_empty_optional_keys():
    from odoo_module_migrate.manifest import format_manifest

    original = '''{
    "name": "Validation",
    "summary": "",
    "description": """
        Validate invoices automatically.
        Keep failures in draft.
    """,
    "external_dependencies": {},
    "demo": [],
    "assets": {},
    "depends": ["account"],
}
'''
    result = format_manifest(original)
    data = ast.literal_eval(result)
    assert "summary" not in data
    assert "external_dependencies" not in data
    assert "demo" not in data
    assert "assets" not in data
    assert '"description": """\n' in result
    assert "        Validate invoices automatically." in result
    assert format_manifest(result) == result


def test_scheduled_action_method_must_come_from_dependencies(tmp_path):
    addon(
        tmp_path,
        "account",
        code="class Move(Model):\n    _name = 'account.move'\n",
    )
    addon(
        tmp_path,
        "account_invoice_extract",
        ["account"],
        code="class Move(Model):\n    _inherit = 'account.move'\n    def _cron_validate(self): pass\n",
    )
    mod = addon(
        tmp_path,
        "custom",
        ["account"],
        code="class Move(Model):\n    _inherit = 'account.move'\n    def _cron_validate_invoices(self): pass\n",
        xml="""<record id="cron" model="ir.cron">
<field name="model_id" ref="account.model_account_move"/>
<field name="code">model._cron_validate()</field>
</record>""",
    )
    index = models.ModelIndex.build([tmp_path])
    issues = list(python_checks.check_module(mod, index))
    action_issues = [
        issue for issue in issues if "Scheduled/server action" in issue[-1]
    ]
    assert len(action_issues) == 1
    assert action_issues[0][2] == "warning"
    assert "account_invoice_extract" in action_issues[0][-1]
    assert "outside this module's dependencies" in action_issues[0][-1]

    (mod / "view.xml").write_text(
        (mod / "view.xml")
        .read_text()
        .replace("model._cron_validate()", "model._cron_validate_invoices()")
    )
    assert not [
        issue
        for issue in python_checks.check_module(mod, index)
        if "Scheduled/server action" in issue[-1]
    ]


def test_product_view_detailed_type_values_are_migrated(tmp_path):
    xml = """<record id="form" model="ir.ui.view">
<field name="model">product.template</field>
<field name="arch" type="xml"><form>
<button invisible="detailed_type == 'service'"/>
<button invisible="detailed_type == &quot;consu&quot;"/>
<button invisible="detailed_type != 'consu'"/>
</form></field></record>"""
    mod = addon(tmp_path, "custom", xml=xml)
    migrate_product_storable(
        module_path=mod, tools=tools, logger=logging.getLogger("odoo_module_migrate")
    )
    text = (mod / "view.xml").read_text()
    assert "detailed_type" not in text
    assert "type == 'service'" in text
    assert "type == 'consu' and not is_storable" in text
    assert "(type != 'consu' or is_storable)" in text


def test_unused_import_cleanup_preserves_initializers_and_noqa(tmp_path):
    mod = addon(
        tmp_path,
        "custom",
        code='from odoo import api, models\nclass Partner(models.Model):\n    _inherit = "res.partner"\n',
    )
    (mod / "__init__.py").write_text("from . import models\n")
    (mod / "hook.py").write_text("import registration  # noqa: F401\n")
    migration = Migration(
        tmp_path,
        "19.0",
        "20.0",
        ["custom"],
        commit_enabled=False,
        pre_commit=False,
        clean_imports=True,
    )
    migration._format_changed_files()
    assert "from odoo import models" in (mod / "models.py").read_text()
    assert "api" not in (mod / "models.py").read_text()
    assert (mod / "__init__.py").read_text() == "from . import models\n"
    assert "import registration" in (mod / "hook.py").read_text()


def test_import_only_initializers_have_no_blank_lines(tmp_path):
    mod = addon(tmp_path, "custom")
    models = mod / "models"
    models.mkdir()
    initializer = models / "__init__.py"
    initializer.write_text(
        "\nfrom . import partner\n\n\n# models grouped before\n\nfrom . import product\n\n",
        encoding="utf-8",
    )
    quality.finish_module(mod)
    assert initializer.read_text(encoding="utf-8") == (
        "from . import partner\n# models grouped before\nfrom . import product\n"
    )


def test_initializer_with_runtime_code_keeps_internal_spacing(tmp_path):
    mod = addon(tmp_path, "custom")
    initializer = mod / "__init__.py"
    initializer.write_text(
        "\nVALUE = '''first\n\nsecond'''\n\nregister(VALUE)\n",
        encoding="utf-8",
    )
    quality.finish_module(mod)
    assert "first\n\nsecond" in initializer.read_text(encoding="utf-8")


def test_transitive_merged_dependencies_are_resolved(tmp_path):
    addon(tmp_path, "custom", ["bridge"])
    migration = Migration(
        tmp_path, "19.0", "20.0", ["custom"], commit_enabled=False, pre_commit=False
    )
    index = views.ViewIndex()
    index.depends = {
        "custom": ["bridge"],
        "bridge": ["stock_picking_batch"],
        "stock": ["base"],
        "base": [],
    }
    migration._resolve_index_dependencies(index)
    assert not index.unknown_dependencies("custom")
    assert "stock" in index.closure("custom")


def test_accessible_dependency_files_not_iterated_by_official_scripts(tmp_path):
    from types import SimpleNamespace
    from odoo_module_migrate.upgrade_code import runner

    class Manager:
        def get_file(self, module, filename):
            return self._files[module]

    uc = SimpleNamespace(FileManager=Manager)
    runner.patch_file_manager(uc, set())
    manager = Manager()
    target = tmp_path / "custom"
    manager._target_roots = (target,)
    manager._modules = {"custom": target, "base": tmp_path / "base"}
    manager._files = {
        name: SimpleNamespace(path=path / "models.py", dirty=False)
        for name, path in manager._modules.items()
    }
    assert list(manager) == [manager._files["custom"]]
    assert manager.get_file("base", "models.py") is manager._files["base"]
