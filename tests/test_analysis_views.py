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
        _view("v3", "web.form", "<xpath expr=\"//div[@name='buttons']/button[@name='action_ok']\" position=\"after\"/>"),
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


def test_bare_tag_anchors(tmp_path):
    """<header position="inside"> and //header need such an element in the
    target view (product.product_normal_form_view has no <header> in 20.0,
    odoo 4c8bf7a7a90f); what the view inserts itself counts."""
    ref, custom = tmp_path / "odoo", tmp_path / "custom"
    _module(ref, "base", [], "")
    _module(ref, "product", ["base"], _view(
        "form", None, '<form><sheet><group name="g"><field name="name"/></group></sheet></form>'))
    mod = _module(custom, "my_mod", ["product"], "".join([
        _view("v1", "product.form", '<header position="inside"><field name="x"/></header>'),
        _view("v3", "product.form", '<xpath expr="//form[1]/sheet[1]/group[2]" position="after"/>'),
        _view("v4", "product.form", '<sheet position="inside"><div class="x"/></sheet>'),
        # inserted by the view itself, then used as an anchor
        _view("v5", "product.form",
              '<sheet position="before"><footer><button name="b"/></footer></sheet>'
              '<xpath expr="//footer/button[@name=\'b\']" position="after"/>'),
        _view("v6", "product.form", "<xpath expr=\"//div[hasclass('x')]/..\" position=\"after\"/>"),
    ]))
    mod2 = _module(custom, "my_mod2", ["product"],
                   _view("v2", "product.form", '<xpath expr="//header" position="inside"/>'))
    index = views.ViewIndex.build([ref, custom])
    for module in (mod, mod2):
        messages = [msg for _p, _l, msg in views.check_module(module, index, {"base", "product"})]
        assert [m.split(" ")[0] for m in messages] == ["<header>"], messages


def test_bare_tag_anchors_templates(tmp_path):
    ref, custom = tmp_path / "odoo", tmp_path / "custom"
    _module(ref, "base", [], "")
    _module(ref, "web", ["base"], '<template id="layout"><div><span/></div></template>')
    mod = _module(custom, "my_web", ["web"], "".join([
        '<template id="t1" inherit_id="web.layout"><xpath expr="/t/div/span" position="after"/></template>',
        '<template id="t2" inherit_id="web.layout"><xpath expr="//h2" position="replace"/></template>',
    ]))
    index = views.ViewIndex.build([ref, custom])
    messages = [msg for _p, _l, msg in views.check_module(mod, index, {"base", "web"})]
    assert len(messages) == 1 and messages[0].startswith("<h2> not found"), messages


def test_parent_view_of_a_module_outside_depends(tmp_path):
    """A module inherits a view of another custom module without depending
    on it: the dependency is reported, not its anchors."""
    ref, custom = tmp_path / "odoo", tmp_path / "custom"
    _module(ref, "base", [], "")
    _module(custom, "x_base", ["base"], _view(
        "task_form", None, '<form><field name="input_type"/></form>', "x.task")
        + '<record id="menu_x" model="ir.ui.menu"><field name="name">x</field></record>')
    mod = _module(custom, "x_ext", ["base"], _view(
        "v1", "x_base.task_form", '<field name="input_type" position="after"/>', "x.task")
        + '<menuitem id="m" parent="x_base.menu_x"/>'
        + '<menuitem id="m2" parent="x_base.menu_unknown"/>')
    # with the dependency: nothing
    mod_ok = _module(custom, "x_ext_ok", ["x_base"], _view(
        "v1", "x_base.task_form", '<field name="input_type" position="after"/>', "x.task"))
    # a dependency not indexed: x_base may be one of its dependencies
    mod_unknown = _module(custom, "x_ext_unknown", ["not_indexed"], _view(
        "v1", "x_base.task_form", '<field name="input_type" position="after"/>', "x.task"))
    index = views.ViewIndex.build([ref, custom])
    messages = sorted(msg for _p, _l, msg in views.check_module(mod, index, {"base"}))
    assert messages == [
        "XML id x_base.menu_x comes from the module 'x_base', which is not in the"
        " dependencies of the module: add it to 'depends'",
        "parent view x_base.task_form comes from the module 'x_base', which is not in"
        " the dependencies of the module: add it to 'depends'",
    ], messages
    assert not list(views.check_module(mod_ok, index, {"base"}))
    assert not list(views.check_module(mod_unknown, index, {"base"}))


def test_anchor_added_by_a_previous_spec_of_the_same_view(tmp_path):
    # a spec anchored on an element added
    # by a previous spec of the same view is valid (specs applied in order)
    ref, custom = tmp_path / "odoo", tmp_path / "custom"
    _module(ref, "base", [], _view("form", None, '<form><field name="name"/></form>', "res.partner"))
    mod = _module(custom, "my_mod", ["base"], _view("v1", "base.form", (
        "<xpath expr=\"//field[@name='name']\" position=\"after\"><field name=\"code\"/></xpath>"
        "<xpath expr=\"//field[@name='code']\" position=\"after\"><field name=\"ape\"/></xpath>"
        '<field name="ape" position="after"><div><field name="ref_type"/></div></field>'
        # anchored on an element only added AFTER it: does not install
        "<xpath expr=\"//field[@name='late']\" position=\"after\"/>"
        '<field name="ref_type" position="after"><field name="late"/></field>'
        # attributes do not add elements
        '<field name="late" position="attributes"><attribute name="name">renamed</attribute></field>'
        "<xpath expr=\"//field[@name='renamed']\" position=\"after\"/>"
        # the children of a <data> are applied after the other specs
        '<data><field name="z" position="after"/></data>'
        '<field name="late" position="after"><field name="z"/></field>'
    ), "res.partner"))
    index = views.ViewIndex.build([ref, custom])
    messages = [msg for _p, _l, msg in views.check_module(mod, index, {"base"})]
    assert len(messages) == 2, messages
    assert messages[0].startswith("field[@name='late'] not found")
    assert messages[1].startswith("field[@name='renamed'] not found")


def test_dependency_outside_the_addons_paths(tmp_path):
    # my_mod depends on unknown_module, absent from the addons paths: its own
    # dependencies (product...) are unknown and it may add any anchor:
    # anchors and dependencies of the
    # XML ids are not checked, what must exist in Odoo itself still is
    ref, custom = tmp_path / "odoo", tmp_path / "custom"
    _module(ref, "base", [], "")
    _module(ref, "product", ["base"], _view("form", None, '<form><field name="name"/></form>')
            + '<record id="menu_p" model="ir.ui.menu"><field name="name">p</field></record>')
    _module(ref, "other", ["product"], _view("form_x", "product.form",
            '<field name="name" position="after"><field name="default_code"/></field>'))
    mod = _module(custom, "my_mod", ["unknown_module"], "".join([
        _view("v1", "product.form", "<xpath expr=\"//field[@name='default_code']\" position=\"after\"/>"),
        _view("v2", "product.form", "<xpath expr=\"//field[@name='custom_field']\" position=\"after\"/>"),
        _view("v3", "product.gone", "<xpath expr=\"//field[@name='name']\" position=\"after\"/>"),
        '<record id="product.menu_p" model="ir.ui.menu"><field name="active" eval="False"/></record>',
        '<record id="product.menu_gone" model="ir.ui.menu"><field name="active" eval="False"/></record>',
    ]))
    index = views.ViewIndex.build([ref, custom])
    assert index.unknown_dependencies("my_mod") == ["unknown_module"]
    messages = sorted(msg for _p, _l, msg in views.check_module(mod, index, {"base", "product", "other"}))
    assert messages == [
        "XML id product.menu_gone does not exist in the target Odoo",
        "parent view product.gone does not exist in the target Odoo",
    ]
