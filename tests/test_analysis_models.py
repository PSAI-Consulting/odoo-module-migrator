# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo_module_migrate.analysis import models


def _module(root, name, depends, py):
    path = root / name
    (path / "models").mkdir(parents=True)
    (path / "__manifest__.py").write_text(repr({"name": name, "depends": depends}), encoding="utf-8")
    (path / "models" / "models.py").write_text(py, encoding="utf-8")
    return path


def test_missing_models(tmp_path):
    ref, custom = tmp_path / "odoo", tmp_path / "custom"
    _module(ref, "base", [], "class P(Model):\n    _name = 'res.partner'\n")
    # Python 3.12 only syntax: the model names are still read
    _module(ref, "stock", ["base"], "type Alias = int\nclass M(Model):\n    _name = 'stock.move'\n")
    _module(ref, "other", ["base"], "class O(Model):\n    _name = 'other.model'\n")
    mod = _module(custom, "my_mod", ["stock"], (
        "from odoo import fields, models\n"
        "class A(models.Model):\n"
        "    _inherit = 'stock.move'\n"
        "    partner_id = fields.Many2one('res.partner')\n"
        "    layer_ids = fields.One2many('stock.valuation.layer', 'move_id')\n"
        "class B(models.Model):\n"
        "    _name = 'my.model'\n"
        "    _inherit = ['mail.thread', 'other.model']\n"
        "    own_id = fields.Many2one(comodel_name='my.model')\n"
    ))
    index = models.ModelIndex.build([ref, custom])
    found = sorted((line, msg.split("'")[1]) for _p, line, msg in models.check_module(mod, index))
    # stock.valuation.layer removed; mail.thread and other.model not in the
    # dependencies (other is not a dependency of my_mod)
    assert found == [(5, "stock.valuation.layer"), (6, "mail.thread"), (6, "other.model")]


def test_model_of_a_module_outside_depends(tmp_path):
    """The model exists in another indexed module, not in the dependencies:
    name the module to add to 'depends'."""
    ref, custom = tmp_path / "odoo", tmp_path / "custom"
    _module(ref, "base", [], "class P(Model):\n    _name = 'res.partner'\n")
    _module(custom, "x_product", ["base"], "class F(Model):\n    _name = 'x.family'\n")
    py = (
        "from odoo import fields, models\n"
        "class A(models.Model):\n"
        "    _name = 'x.agreement'\n"
        "    family_id = fields.Many2one('x.family')\n"
    )
    mod = _module(custom, "my_mod", ["base"], py)
    # a dependency is not indexed: the model may come from it, nothing reported
    mod2 = _module(custom, "my_mod2", ["unknown_mod"], py)
    index = models.ModelIndex.build([ref, custom])
    messages = [msg for _p, _l, msg in models.check_module(mod, index)]
    assert len(messages) == 1 and "defined by the module(s) x_product" in messages[0], messages
    messages = [msg for _p, _l, msg in models.check_module(mod2, index)]
    assert messages == [], messages


FIELDS_PY = '''from odoo import api, fields, models


class Move(models.Model):
    _name = "account.move"
    _inherit = ["mail.thread"]

    line_ids = fields.One2many("account.move.line", "move_id")
    partner_id = fields.Many2one("res.partner")


class Line(models.Model):
    _name = "account.move.line"

    move_id = fields.Many2one("account.move")
    name = fields.Char()


class Thread(models.AbstractModel):
    _name = "mail.thread"

    message_ids = fields.One2many("mail.message", "res_id")


class Wizard(models.TransientModel):
    _name = "account.wizard"

    move_id = fields.Many2one("account.move")
'''

CUSTOM_PY = '''from odoo import api, fields, models


class Move(models.Model):
    _inherit = "account.move"

    blocked = fields.Boolean(compute="_compute_blocked")
    x_name = fields.Char(related="line_ids.name")
    bad_name = fields.Char(related="partner_id.gone")

    @api.depends("line_ids", "line_ids.blocked", "message_ids", "display_name", "partner_id.name")
    def _compute_blocked(self):
        pass


class Wizard(models.TransientModel):
    _inherit = "account.wizard"

    @api.depends("move_id.gone")
    def _compute_x(self):
        pass


class Mixin(models.AbstractModel):
    _name = "x.mixin"

    @api.depends("company_id")
    def _compute_y(self):
        pass
'''


def test_field_paths(tmp_path):
    """account.move.line.blocked removed in 18.0 (odoo 67dc71588751): a path of
    @api.depends / related= through it prevents the registry from loading."""
    ref, custom = tmp_path / "odoo", tmp_path / "custom"
    _module(ref, "base", [], "class P(Model):\n    _name = 'res.partner'\n    name = fields.Char()\n")
    _module(ref, "account", ["base"], FIELDS_PY)
    mod = _module(custom, "my_mod", ["account"], CUSTOM_PY)
    mod_unknown = _module(custom, "my_mod2", ["not_indexed"], CUSTOM_PY)
    index = models.ModelIndex.build([ref, custom])
    found = sorted((line, msg.split("'")[1], msg.split("'")[3])
                   for _p, line, msg in models.check_field_paths(mod, index))
    # name of res.partner, display_name, message_ids (parent): found; the
    # transient model on a regular one and the mixin are not checked
    assert found == [(9, "partner_id.gone", "gone"), (11, "line_ids.blocked", "blocked")], found
    assert not list(models.check_field_paths(mod_unknown, index))


def test_dependency_outside_the_addons_paths(tmp_path):
    # my_mod depends on other_addon, absent from the addons paths, which may
    # define other.unit...: nothing can be reported
    ref, custom = tmp_path / "odoo", tmp_path / "custom"
    _module(ref, "base", [], "class P(Model):\n    _name = 'res.partner'\n")
    mod = _module(custom, "my_mod", ["base", "other_addon"], (
        "class A(models.Model):\n"
        "    _inherit = 'other.unit'\n"
        "    partner_id = fields.Many2one('other.region')\n"
    ))
    index = models.ModelIndex.build([ref, custom])
    assert index.unknown_dependencies("my_mod") == ["other_addon"]
    assert list(models.check_module(mod, index)) == []
