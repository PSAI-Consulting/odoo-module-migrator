# Copyright (C) 2019 - Today: GRAP (http://www.grap.coop)
# @author: Sylvain LE GAL (https://twitter.com/legalsylvain)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo_module_migrate.base_migration_script import BaseMigrationScript

# TODO: Call 2to3

_TEXT_REPLACES = {
    "*": {
        r"ir.actions.report.xml": "ir.actions.report",
        r"report.external_layout": "web.external_layout",
        r"report.html_container": "web.html_container",
        r"report.layout": "web.report_layout",
        r"report.minimal_layout": "web.minimal_layout",
    },
    ".xml": {
        r"kanban_state_selection": "state_selection",
    },
}

_TEXT_ERRORS = {
    "*": {
        "('|\")workflow('|\")": "[V11] Reference to 'workflow'."
        " This model has been removed.",
        "('|\")workflow.activity('|\")": "[V11] Reference to 'workflow.activity'."
        " This model has been removed.",
        "('|\")workflow.instance('|\")": "[V11] Reference to'workflow.instance'."
        " This model has been removed.",
        "('|\")workflow.transition('|\")": "[V11] Reference to 'workflow.transition'."
        " This model has been removed.",
        "('|\")workflow.triggers('|\")": "[V11] Reference to 'workflow.triggers'."
        " This model has been removed.",
        "('|\")workflow.workitem('|\")": "[V11] Reference to 'workflow.workitem'."
        " This model has been removed.",
        "report.external_layout_header": "report.external_layout_header is obsolete.",
        "report.external_layout_footer": "report.external_layout_footer is obsolete.",
    },
    ".xml": {
        r"<tree[\s][^>]*colors=": "colors attribute is deprecated in tree view."
        " Use decoration- instead.",
        r"<tree[\s][^>]*fonts=": "fonts attribute is deprecated in tree view."
        " Use decoration- instead.",
    },
}

# Modules: deprecated_modules/migrate_100_110/*.yaml


class MigrationScript(BaseMigrationScript):

    _TEXT_REPLACES = _TEXT_REPLACES
    _TEXT_ERRORS = _TEXT_ERRORS
