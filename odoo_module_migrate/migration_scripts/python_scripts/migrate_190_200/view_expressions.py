"""Safe Odoo 20 view syntax updates independent of client model names."""

import re


VIEW_RECORD_RE = re.compile(
    r"<record\b(?=[^>]*\bmodel\s*=\s*(['\"])ir\.ui\.view\1)[^>]*>[\s\S]*?</record>"
)
TAG_RE = re.compile(r"<!--[\s\S]*?-->|<[^>]+>")
EXPRESSION_ATTRIBUTE_RE = re.compile(
    r"\b(context|domain|invisible|readonly|required)\s*=\s*(['\"])(.*?)\2"
)


def _migrate_record(text):
    def tag(match):
        value = match[0]
        if value.startswith("<!--"):
            return value
        value = re.sub(
            r"\bwidget\s*=\s*(['\"])DynamicModelFieldSelectorChar\1",
            'widget="field_selector"',
            value,
        )
        if value.lstrip().startswith("<field"):
            value = re.sub(
                r"\s+widget\s*=\s*(['\"])kanban\1", ' mode="kanban"', value
            )
        value = re.sub(
            r"\bstyle\s*=\s*(['\"])(.*?)\1",
            lambda style: (
                f"style={style[1]}{style[2].replace('%%', '%')}{style[1]}"
            ),
            value,
        )
        return EXPRESSION_ATTRIBUTE_RE.sub(
            lambda attr: (
                f"{attr[1]}={attr[2]}"
                + re.sub(r"\bactive_id\b", "id", attr[3])
                + attr[2]
            ),
            value,
        )

    return TAG_RE.sub(tag, text)


def migrate_view_expressions(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".xml",)):
        text = tools._read_content(path)
        new = VIEW_RECORD_RE.sub(lambda match: _migrate_record(match[0]), text)
        if new != text:
            tools._write_content(path, new)
            logger.info("[20] Updated removed view expressions/widgets. File %s", path)
