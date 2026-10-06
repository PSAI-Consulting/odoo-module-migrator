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
    """The model exists in another indexed module, not in the dependencies
    (stof_accords_galec: product.family of easi_product): name the module."""
    ref, custom = tmp_path / "odoo", tmp_path / "custom"
    _module(ref, "base", [], "class P(Model):\n    _name = 'res.partner'\n")
    _module(custom, "easi_product", ["base"], "class F(Model):\n    _name = 'product.family'\n")
    py = (
        "from odoo import fields, models\n"
        "class A(models.Model):\n"
        "    _name = 'sale.accord'\n"
        "    family_id = fields.Many2one('product.family')\n"
    )
    mod = _module(custom, "my_mod", ["base"], py)
    # a dependency is not indexed: the model may come from it, old message
    mod2 = _module(custom, "my_mod2", ["unknown_mod"], py)
    index = models.ModelIndex.build([ref, custom])
    messages = [msg for _p, _l, msg in models.check_module(mod, index)]
    assert len(messages) == 1 and "defined by the module(s) easi_product" in messages[0], messages
    messages = [msg for _p, _l, msg in models.check_module(mod2, index)]
    assert len(messages) == 1 and "does not exist in the target Odoo" in messages[0], messages
