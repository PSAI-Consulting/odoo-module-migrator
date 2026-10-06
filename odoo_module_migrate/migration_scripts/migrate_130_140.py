# Copyright (C) 2020 - Today: Iván Todorovich
# Copyright (C) 2020 - Today: Simone Rubino
# @author: Iván Todorovich (https://twitter.com/ivantodorovich)
# @author: Simone Rubino (https://github.com/Daemo00)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import re
from pathlib import Path
import lxml.etree as et
from odoo_module_migrate.base_migration_script import BaseMigrationScript


# Source: odoo 14.0 removed the <report> and <act_window> XML shortcuts
# (odoo/tools/convert.py has no _tag_report / _tag_act_window anymore). The
# conversion follows the semantics of odoo 13.0 odoo/tools/convert.py
# (_tag_report, _tag_act_window, ir.actions.report.create_action()).
_MODEL_MODULES_FILE = Path(__file__).parent / "data" / "model_modules_140.yaml"
_SHORTCUT_RE = re.compile(
    r"<(?P<tag>report|act_window)\b(?P<attrs>(?:\s+[\w:.-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*/>"
)
_MASK_RE = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>", re.S)
_MODEL_NAME_RE = re.compile(r"""^\s+_name\s*=\s*['"]([\w.]+)['"]""", re.M)
_model_modules = None


class _CannotConvert(Exception):
    pass


def _xml_text(value):
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _model_ref(model, own_models, module_name):
    global _model_modules
    if _model_modules is None:
        import yaml

        _model_modules = yaml.safe_load(_MODEL_MODULES_FILE.read_text(encoding="utf-8")) or {}
    if model in own_models:
        module = module_name
    elif model in _model_modules:
        module = _model_modules[model]
    else:
        raise _CannotConvert("module of model %s unknown" % model)
    return "%s.model_%s" % (module, model.replace(".", "_"))


def _groups_eval(groups):
    items = []
    for group in groups.split(","):
        group = group.strip()
        if group.startswith("-"):
            items.append("(3, ref('%s'))" % group[1:])
        elif group:
            items.append("(4, ref('%s'))" % group)
    return "[%s]" % ", ".join(items)


def _report_fields(attrs, own_models, module_name):
    """[(field, kind, value)] kind: text / ref / eval (13.0 _tag_report)."""
    for required in ("string", "model", "name"):
        if not attrs.get(required):
            raise _CannotConvert("attribute %s missing" % required)
    fields = [
        ("name", "text", attrs["string"]),
        ("model", "text", attrs["model"]),
        ("report_type", "text", attrs.get("report_type") or "qweb-pdf"),
        ("report_name", "text", attrs["name"]),
    ]
    for attr, field in (("file", "report_file"), ("print_report_name", "print_report_name"),
                        ("attachment", "attachment"), ("usage", "usage")):
        if attrs.get(attr):
            fields.append((field, "text", attrs[attr]))
    for attr in ("attachment_use", "multi", "auto", "header"):
        if attrs.get(attr):
            fields.append((attr, "eval", attrs[attr]))
    if attrs.get("groups"):
        fields.append(("groups_id", "eval", _groups_eval(attrs["groups"])))
    if attrs.get("paperformat"):
        fields.append(("paperformat_id", "ref", attrs["paperformat"]))
    menu = attrs.get("menu")
    if not menu or menu.strip() not in ("False", "0"):
        if menu and menu.strip() not in ("True", "1"):
            raise _CannotConvert("menu=%r" % menu)
        fields.append(("binding_model_id", "ref", _model_ref(attrs["model"], own_models, module_name)))
        fields.append(("binding_type", "text", "report"))
    unknown = set(attrs) - {"id", "string", "model", "name", "report_type", "file",
                            "print_report_name", "attachment", "usage", "attachment_use",
                            "multi", "auto", "header", "groups", "paperformat", "menu"}
    if unknown:
        raise _CannotConvert("attributes %s" % ", ".join(sorted(unknown)))
    return "ir.actions.report", fields


def _act_window_fields(attrs, own_models, module_name):
    """[(field, kind, value)] (13.0 _tag_act_window; src_model / key2 of 12.0)."""
    if not attrs.get("name") or not attrs.get("res_model"):
        raise _CannotConvert("name or res_model missing")
    fields = [("name", "text", attrs["name"]), ("res_model", "text", attrs["res_model"])]
    for attr in ("view_mode", "domain", "context", "target", "usage", "limit"):
        if attrs.get(attr):
            fields.append((attr, "text", attrs[attr]))
    if attrs.get("view_id"):
        fields.append(("view_id", "ref", attrs["view_id"]))
    if attrs.get("groups"):
        fields.append(("groups_id", "eval", _groups_eval(attrs["groups"])))
    binding_model = attrs.get("binding_model") or attrs.get("src_model")
    binding_type = attrs.get("binding_type")
    key2 = attrs.get("key2")
    if key2 and key2 not in ("client_action_multi", "client_print_multi"):
        raise _CannotConvert("key2=%r" % key2)
    if key2 == "client_print_multi":
        binding_type = "report"
    if binding_model:
        fields.append(("binding_model_id", "ref", _model_ref(binding_model, own_models, module_name)))
        if binding_type:
            fields.append(("binding_type", "text", binding_type))
        if attrs.get("binding_views") is not None:
            fields.append(("binding_view_types", "text", attrs["binding_views"]))
    unknown = set(attrs) - {"id", "name", "res_model", "view_mode", "domain", "context", "target",
                            "usage", "limit", "view_id", "groups", "binding_model", "src_model",
                            "binding_type", "key2", "binding_views"}
    if unknown:
        raise _CannotConvert("attributes %s" % ", ".join(sorted(unknown)))
    return "ir.actions.act_window", fields


def _record_text(xmlid, model, fields, indent, step):
    lines = ['<record id="%s" model="%s">' % (xmlid, model)]
    for name, kind, value in fields:
        if kind == "text":
            lines.append('<field name="%s">%s</field>' % (name, _xml_text(value)))
        else:
            lines.append('<field name="%s" %s="%s"/>' % (
                name, kind, _xml_text(value).replace('"', "&quot;")))
    lines.append("</record>")
    return ("\n" + indent).join(
        [lines[0]] + [step + line for line in lines[1:-1]] + [lines[-1]]
    )


def _reformat_file(file_path: Path, own_models=(), module_name="", logger=None):
    """Replace the <report> / <act_window> shortcuts of `file_path` by
    <record> tags, in place (the rest of the file is kept as is)."""
    text = file_path.read_text(encoding="utf-8")
    if "<report" not in text and "<act_window" not in text:
        return None
    try:
        tree = et.fromstring(text.encode("utf-8"))
    except et.XMLSyntaxError:
        return None
    elements = [e for e in tree.iter("report", "act_window")]
    masked = _MASK_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), text)
    matches = list(_SHORTCUT_RE.finditer(masked))
    if len(matches) != len(elements) or any(m["tag"] != e.tag for m, e in zip(matches, elements)):
        if logger:
            logger.error("%s: <report> / <act_window> not converted (XML layout not understood),"
                         " convert them to <record> by hand" % file_path.name)
        return None
    edits = []
    for match, element in zip(matches, elements):
        attrs = dict(element.attrib)
        try:
            if not attrs.get("id"):
                raise _CannotConvert("no id")
            build = _report_fields if element.tag == "report" else _act_window_fields
            model, fields = build(attrs, own_models, module_name)
        except _CannotConvert as error:
            if logger:
                logger.error(
                    "[14] <%s> is not supported anymore: convert it to <record> by hand (%s)."
                    " File %s:%s" % (element.tag, error, file_path.name, element.sourceline))
            continue
        line_start = masked.rfind("\n", 0, match.start()) + 1
        indent = masked[line_start:match.start()]
        indent = indent if not indent.strip() else ""
        edits.append((match.start(), match.end(), _record_text(attrs["id"], model, fields, indent, "    ")))
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    if edits:
        file_path.write_text(text, encoding="utf-8")
        return file_path
    return None


def _get_files(module_path, reformat_file_ext):
    """Get files to be reformatted."""
    file_paths = list()
    if not module_path.is_dir():
        raise Exception(f"'{module_path}' is not a directory")
    file_paths.extend(module_path.rglob("*" + reformat_file_ext))
    return file_paths


def reformat_deprecated_tags(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    """Replace the <act_window> and <report> tags, removed in 14.0, by <record>."""
    own_models = set()
    for py_file in _get_files(module_path, ".py"):
        own_models.update(_MODEL_NAME_RE.findall(py_file.read_text(encoding="utf-8", errors="replace")))
    for file_path in _get_files(module_path, ".xml"):
        if _reformat_file(file_path, own_models, module_name, logger):
            logger.info("[14] <report> / <act_window> converted to <record> in %s" % file_path)


_TEXT_REPLACES = {
    ".js": {
        r"tour\.STEPS\.SHOW_APPS_MENU_ITEM": "tour.stepUtils.showAppsMenuItem()",
        r"tour\.STEPS\.TOGGLE_HOME_MENU": "tour.stepUtils.toggleHomeMenu()",
    },
}


class MigrationScript(BaseMigrationScript):

    _GLOBAL_FUNCTIONS = [reformat_deprecated_tags]
    _TEXT_REPLACES = _TEXT_REPLACES
