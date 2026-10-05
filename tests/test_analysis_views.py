# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo_module_migrate.analysis import views


def _module(root, name, depends, views_xml):
    path = root / name
    (path / "views").mkdir(parents=True)
    (path / "__manifest__.py").write_text(
        repr({"name": name, "depends": depends, "data": ["views/views.xml"]}), encoding="utf-8"
    )
    (path / "views" / "views.xml").write_text(f"<odoo>{views_xml}</odoo>", encoding="utf-8")
    return path


def _view(xid, inherit, arch, model="product.product"):
    inherit_field = f'<field name="inherit_id" ref="{inherit}"/>' if inherit else ""
    return (
        f'<record id="{xid}" model="ir.ui.view"><field name="model">{model}</field>'
        f'{inherit_field}<field name="arch" type="xml">{arch}</field></record>'
    )


def test_anchor_checks(tmp_path):
    ref, custom = tmp_path / "odoo", tmp_path / "custom"
    _module(ref, "base", [], "")
    _module(ref, "product", ["base"], _view("tree", None, '<list><field name="name"/></list>'))
    # adds 'type', but the custom module does not depend on it
    _module(ref, "other", ["product"], _view("tree_x", "product.tree",
            '<field name="name" position="after"><field name="type"/></field>'))
    _module(ref, "stock", ["product"], _view("tree_s", "product.tree",
            '<field name="name" position="after"><field name="qty"/></field>'))
    mod = _module(custom, "my_mod", ["stock"], "".join([
        _view("v1", "product.tree", "<xpath expr=\"//field[@name='type']\" position=\"after\"><field name=\"x\"/></xpath>"),
        _view("v2", "product.tree", '<field name="qty" position="after"><field name="y"/></field>'),
        _view("v3", "product.tree", '<field name="y" position="after"><field name="z"/></field>'),
        _view("v4", "product.missing", '<field name="name" position="after"/>'),
    ]))
    index = views.ViewIndex.build([ref, custom])
    found = [(line, msg.split(" ")[1]) for _p, line, msg in views.check_module(mod, index, {"product", "stock", "other", "base"})]
    messages = " | ".join(msg for _p, _l, msg in views.check_module(mod, index, {"product"}))
    assert "'type'" in messages        # only in a module that is not a dependency
    assert "'qty'" not in messages     # added by stock, a dependency
    assert "'y'" not in messages       # added by v2 of the module itself
    assert "product.missing does not exist" in messages
    assert len(found) == 2


def test_other_anchors_templates_and_xmlids(tmp_path):
    ref, custom = tmp_path / "odoo", tmp_path / "custom"
    _module(ref, "base", [], "")
    _module(ref, "web", ["base"],
            '<template id="layout"><html><t t-set="head_web"/><body/></html></template>'
            '<record id="menu_x" model="ir.ui.menu"><field name="name">x</field></record>'
            + _view("form", None, '<form><button name="action_ok"/><div name="buttons"/></form>'))
    mod = _module(custom, "my_web", ["web"], "".join([
        '<template id="t1" inherit_id="web.layout"><xpath expr="//t[@t-set=\'head_web\']" position="after"/></template>',
        '<template id="t2" inherit_id="web.layout"><xpath expr="//t[@t-set=\'gone\']" position="after"/></template>',
        _view("v1", "web.form", "<xpath expr=\"//button[@name='action_ok']\" position=\"after\"/>"),
        _view("v2", "web.form", '<button name="action_gone" position="after"><span/></button>'),
        '<record id="web.menu_x" model="ir.ui.menu"><field name="active" eval="False"/></record>',
        '<record id="web.menu_gone" model="ir.ui.menu"><field name="active" eval="False"/></record>',
    ]))
    index = views.ViewIndex.build([ref, custom])
    messages = sorted(msg for _p, _l, msg in views.check_module(mod, index, {"base", "web"}))
    assert len(messages) == 3, messages
    assert "XML id web.menu_gone does not exist" in messages[0]
    assert messages[1].startswith("button[@name='action_gone'] not found")
    assert messages[2].startswith("t[@t-set='gone'] not found")
