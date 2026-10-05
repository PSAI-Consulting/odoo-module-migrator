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
