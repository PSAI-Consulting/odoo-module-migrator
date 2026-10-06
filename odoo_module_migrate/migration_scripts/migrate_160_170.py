# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo_module_migrate.base_migration_script import BaseMigrationScript
import lxml.etree as et
from pathlib import Path
import ast
import re
from typing import Any

empty_list = ast.parse("[]").body[0].value

# 17.0 signature: _read_group(domain, groupby, aggregates, having, offset, limit, order)
# Source: odoo 17.0 odoo/models.py, BaseModel._read_group
_AGGREGATE_RE = re.compile(
    r"^(__count|\w+(\.\w+)*:(sum|avg|max|min|count|count_distinct|array_agg"
    r"|recordset|bool_and|bool_or|sum_currency))$"
)


def _str_items(node):
    if isinstance(node, (ast.List, ast.Tuple)):
        return [
            elt.value for elt in node.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ]
    return []


def _is_migrated_read_group(node: ast.Call) -> bool:
    """Whether a _read_group() call already uses the 17.0 signature.

    Makes the transformation idempotent: '__count' or 'field:agg' items can
    only be aggregates (17.0), never 16.0 groupby specs ('date:month').
    """
    keywords = {kw.arg for kw in node.keywords}
    if "lazy" in keywords:
        return False
    if keywords & {"aggregates", "having"}:
        return True
    if len(node.args) >= 3:
        items = _str_items(node.args[2])
        return bool(items) and all(_AGGREGATE_RE.match(item) for item in items)
    return False


def _read_group_calls(tree):
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in ("_read_group", "read_group")
    ]
    return sorted(calls, key=lambda n: (n.lineno, n.col_offset))


def _spans(calls, flags):
    return [
        (n.lineno, n.col_offset, n.end_lineno, n.end_col_offset)
        for n, migrated in zip(calls, flags)
        if migrated
    ]


class AbstractVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        # ((line, line_end, col_offset, end_col_offset), replace_by) NO OVERLAPS
        self.change_todo = []
        self.skip_spans = []

    def post_process(self, all_code: str, file: str) -> str:
        all_lines = all_code.split("\n")
        for (lineno, line_end, col_offset, end_col_offset), new_substring in sorted(
            self.change_todo, reverse=True
        ):
            if lineno == line_end:
                line = all_lines[lineno - 1]
                all_lines[lineno - 1] = (
                    line[:col_offset] + new_substring + line[end_col_offset:]
                )
            else:
                print(
                    f"Ignore replacement {file}: {(lineno, line_end, col_offset, end_col_offset), new_substring}"
                )
        return "\n".join(all_lines)

    def add_change(self, old_node: ast.AST, new_node: ast.AST | str):
        start = (old_node.lineno, old_node.col_offset)
        for line, col, end_line, end_col in self.skip_spans:
            if (line, col) <= start <= (end_line, end_col):
                return  # inside an already migrated call
        position = (
            old_node.lineno,
            old_node.end_lineno,
            old_node.col_offset,
            old_node.end_col_offset,
        )
        if isinstance(new_node, str):
            self.change_todo.append((position, new_node))
        else:
            self.change_todo.append((position, ast.unparse(new_node)))


class VisitorToPrivateReadGroup(AbstractVisitor):
    def post_process(self, all_code: str, file: str) -> str:
        all_lines = all_code.split("\n")
        for i, line in enumerate(all_lines):
            if "super(" not in line:
                all_lines[i] = line.replace(".read_group(", "._read_group(")
        return "\n".join(all_lines)


class VisitorInverseGroupbyFields(AbstractVisitor):
    def visit_Call(self, node: ast.Call) -> Any:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "_read_group":
            # Should have the same number of args/keywords
            # Inverse fields/groupby order
            keywords_by_key = {keyword.arg: keyword.value for keyword in node.keywords}
            key_i_by_key = {keyword.arg: i for i, keyword in enumerate(node.keywords)}
            if len(node.args) >= 3:
                self.add_change(node.args[2], node.args[1])
                self.add_change(node.args[1], node.args[2])
            elif len(node.args) == 2:
                new_args_value = keywords_by_key.get("groupby", empty_list)
                if "groupby" in keywords_by_key:
                    fields_args = ast.keyword("fields", node.args[1])
                    self.add_change(node.args[1], new_args_value)
                    self.add_change(node.keywords[key_i_by_key["groupby"]], fields_args)
                else:
                    self.add_change(
                        node.args[1],
                        f"{ast.unparse(new_args_value)}, {ast.unparse(node.args[1])}",
                    )
            else:  # len(node.args) <= 2
                if (
                    "groupby" in key_i_by_key
                    and "fields" in key_i_by_key
                    and key_i_by_key["groupby"] > key_i_by_key["fields"]
                ):
                    self.add_change(
                        node.keywords[key_i_by_key["groupby"]],
                        node.keywords[key_i_by_key["fields"]],
                    )
                    self.add_change(
                        node.keywords[key_i_by_key["fields"]],
                        node.keywords[key_i_by_key["groupby"]],
                    )
                else:
                    # Check if code is already migrated (has 'aggregates' instead of 'fields')
                    if "aggregates" in key_i_by_key and "groupby" in key_i_by_key:
                        # Code is already migrated, skip this transformation
                        pass
                    else:
                        raise ValueError(f"{key_i_by_key}, {keywords_by_key}, {node.args}")
        self.generic_visit(node)


class VisitorRenameKeywords(AbstractVisitor):
    def visit_Call(self, node: ast.Call) -> Any:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "_read_group":
            # Replace fields by aggregate and orderby by order
            for keyword in node.keywords:
                if keyword.arg == "fields":
                    new_keyword = ast.keyword("aggregates", keyword.value)
                    self.add_change(keyword, new_keyword)
                if keyword.arg == "orderby":
                    new_keyword = ast.keyword("order", keyword.value)
                    self.add_change(keyword, new_keyword)
        self.generic_visit(node)


class VisitorRemoveLazy(AbstractVisitor):
    def post_process(self, all_code: str, file: str) -> str:
        # remove extra comma ',' and extra line if possible
        all_code = super().post_process(all_code, file)
        all_lines = all_code.split("\n")
        for (lineno, __, col_offset, __), __ in sorted(self.change_todo, reverse=True):
            comma_find = False
            line = all_lines[lineno - 1]
            remaining = line[col_offset:]
            line = line[:col_offset]
            while not comma_find:
                if "," not in line:
                    all_lines.pop(lineno - 1)
                    lineno -= 1
                    line = all_lines[lineno - 1]
                else:
                    comma_find = True
            last_index_comma = -(line[::-1].index(",") + 1)
            all_lines[lineno - 1] = line[:last_index_comma] + remaining

        return "\n".join(all_lines)

    def visit_Call(self, node: ast.Call) -> Any:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "_read_group":
            # Replace fields by aggregate and orderby by order
            if len(node.args) == 7:
                self.add_change(node.args[6], "")
            else:
                for keyword in node.keywords:
                    if keyword.arg == "lazy":
                        self.add_change(keyword, "")
        self.generic_visit(node)


class VisitorAggregatesSpec(AbstractVisitor):
    def visit_Call(self, node: ast.Call) -> Any:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "_read_group":

            keywords_by_key = {keyword.arg: keyword.value for keyword in node.keywords}
            aggregate_values = None
            if len(node.args) >= 3:
                aggregate_values = node.args[2]
            elif "aggregates" in keywords_by_key:
                aggregate_values = keywords_by_key["aggregates"]

            groupby_values = empty_list
            if len(node.args) >= 2:
                groupby_values = node.args[1]
            elif "groupby" in keywords_by_key:
                groupby_values = keywords_by_key["groupby"]

            if aggregate_values:
                aggregates = None
                try:
                    aggregates = ast.literal_eval(ast.unparse(aggregate_values))
                    if not isinstance(aggregates, (list, tuple)):
                        raise ValueError(
                            f"{aggregate_values} is not a list but literal ?"
                        )

                    aggregates = [
                        f"{field_spec.split('(')[1][:-1]}:{field_spec.split(':')[1].split('(')[0]}"
                        if "(" in field_spec
                        else field_spec
                        for field_spec in aggregates
                    ]
                    aggregates = [
                        "__count"
                        if field_spec in ("id:count", "id:count_distinct")
                        else field_spec
                        for field_spec in aggregates
                    ]

                    groupby = ast.literal_eval(ast.unparse(groupby_values))
                    if isinstance(groupby, str):
                        groupby = [groupby]

                    aggregates = [
                        f"{field}:sum"
                        if (":" not in field and field != "__count")
                        else field
                        for field in aggregates
                        if field not in groupby
                    ]
                    if not aggregates:
                        aggregates = ["__count"]
                except SyntaxError:
                    pass
                except ValueError:
                    pass

                if aggregates is not None:
                    self.add_change(aggregate_values, repr(aggregates))
        self.generic_visit(node)


Steps_visitor: list[AbstractVisitor] = [
    VisitorToPrivateReadGroup,
    VisitorInverseGroupbyFields,
    VisitorRenameKeywords,
    VisitorAggregatesSpec,
    VisitorRemoveLazy,
]


def replace_read_group_signature(logger, filename):
    with open(filename, mode="rt", encoding="utf-8") as file:
        new_all = all_code = file.read()
        if ".read_group(" in all_code or "._read_group(" in all_code:
            # Decided once on the original code: the steps below change the
            # calls, which would make them look migrated afterwards.
            migrated_flags = [
                _is_migrated_read_group(n)
                for n in _read_group_calls(ast.parse(all_code))
            ]
            for Step in Steps_visitor:
                visitor = Step()
                try:
                    tree = ast.parse(new_all)
                    visitor.skip_spans = _spans(_read_group_calls(tree), migrated_flags)
                    visitor.visit(tree)
                except Exception:
                    logger.info(
                        f"ERROR in {filename} at step {visitor.__class__}: \n{new_all}"
                    )
                    raise
                new_all = visitor.post_process(new_all, filename)
            if new_all == all_code:
                logger.info("read_group detected but not changed in file %s" % filename)

    if new_all != all_code:
        logger.info("Script read_group replace applied in file %s" % filename)
        with open(filename, mode="wt", encoding="utf-8") as file:
            file.write(new_all)


def _get_files(module_path, reformat_file_ext):
    """Get files to be reformatted."""
    file_paths = list()
    if not module_path.is_dir():
        raise Exception(f"'{module_path}' is not a directory")
    file_paths.extend(module_path.rglob("*" + reformat_file_ext))
    return file_paths


def _check_open_form_view(logger, file_path: Path):
    """Check if the view has a button to open a form reg in a tree view `file_path`."""
    parser = et.XMLParser(remove_blank_text=True)
    tree = et.parse(str(file_path.resolve()), parser)
    root_node = tree.getroot()
    
    # Check if root has children
    if len(root_node) == 0:
        return
        
    record_node = root_node[0]
    f_arch = record_node.find('field[@name="arch"]')
    root = f_arch if f_arch is not None else record_node
    for button in root.findall(".//button[@name='get_formview_action']"):
        logger.warning(
            (
                "Button to open a form reg form a tree view detected in file %s line %s, probably should be changed by open_form_view='True'. More info here https://github.com/odoo/odoo/commit/258e6a019a21042bf4f6cf70fcce386d37afd50c"
            )
            % (file_path.name, button.sourceline)
        )


# Source : odoo 17.0 odoo/addons/base/models/ir_ui_view.py : « Since 17.0, the "attrs"
# and "states" attributes are no longer used. »
# Semantics kept from odoo 16.0 odoo/addons/base/models/ir_ui_view.py,
# transfer_node_to_modifiers():
# - states="a,b" adds ('state', 'not in', [a, b]) to the invisible domain of attrs
#   (implicit AND) or is the invisible domain;
# - a static invisible/readonly/required="1" wins over the domain, "0" gives way;
# - a static invisible in a list (outside <header>) is column_invisible.
_ARCH_XPATH = "record[@model='ir.ui.view']/field[@name='arch']"
_START_TAG_RE = re.compile(
    r"<(?P<tag>[\w:.-]+)(?P<attrs>(?:\s+[\w:.-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*/?>"
)
_XML_ATTR_RE = re.compile(r"(?P<sep>\s+)(?P<name>[\w:.-]+)\s*=\s*(?P<q>[\"'])(?P<value>.*?)(?P=q)", re.S)
_MASK_RE = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>", re.S)


class _CannotConvert(Exception):
    pass


def _leaf_to_python(leaf):
    if not isinstance(leaf, ast.Tuple | ast.List) or len(leaf.elts) != 3:
        raise _CannotConvert(f"malformed leaf {ast.unparse(leaf)}")
    left, operator, right = leaf.elts
    if not isinstance(left, ast.Constant) or not isinstance(operator, ast.Constant):
        raise _CannotConvert(f"malformed leaf {ast.unparse(leaf)}")
    if operator.value in ("!=", "="):
        if isinstance(right, ast.Constant) and isinstance(right.value, bool):
            falsy = (operator.value == "=") != right.value
            return f"not {left.value}" if falsy else str(left.value)
        if isinstance(right, ast.List) and not right.elts:
            return f"not {left.value}" if operator.value == "=" else str(left.value)
    if operator.value not in ("=", "!=", "<", ">", "<=", ">=", "in", "not in"):
        raise _CannotConvert(f"operator {operator.value!r}")
    op = "==" if operator.value == "=" else operator.value
    return f"{left.value} {op} {ast.unparse(right)}"


def _get_operand(elts):
    """Elements of the first operand (prefix notation) of a domain."""
    if not elts:
        raise _CannotConvert("missing operand")
    first = elts[0]
    if isinstance(first, ast.Constant) and first.value in ("&", "|", "!"):
        left = _get_operand(elts[1:])
        if first.value == "!":
            return [first] + left
        right = _get_operand(elts[1 + len(left):])
        return [first] + left + right
    return [first]


def _domain_to_python(elts):
    """Python expression of a domain (implicit AND between the operands)."""
    parts = []
    while elts:
        operand = _get_operand(elts)
        elts = elts[len(operand):]
        first = operand[0]
        if isinstance(first, ast.Constant) and first.value == "!":
            parts.append(f"not ({_domain_to_python(operand[1:])})")
        elif isinstance(first, ast.Constant) and first.value in ("&", "|"):
            left = _get_operand(operand[1:])
            right = operand[1 + len(left):]
            word = " and " if first.value == "&" else " or "
            parts.append(f"({_domain_to_python(left)}{word}{_domain_to_python(right)})")
        else:
            parts.append(_leaf_to_python(first))
    return " and ".join(parts)


def _attrs_to_expressions(attrs_string):
    """{attribute: python expression} of attrs="{...}" (raises _CannotConvert)."""
    try:
        expression = ast.parse(attrs_string.strip(), mode="eval").body
    except SyntaxError:
        raise _CannotConvert("attrs is not a python dict")
    if not isinstance(expression, ast.Dict) or None in expression.keys:
        raise _CannotConvert("attrs is not a python dict")
    result = {}
    for key, value in zip(expression.keys, expression.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise _CannotConvert(f"key {ast.unparse(key)}")
        if isinstance(value, ast.Constant) and isinstance(value.value, bool | int):
            result[key.value] = str(bool(value.value))
        elif isinstance(value, ast.List | ast.Tuple):
            result[key.value] = _domain_to_python(value.elts) or "False"
        else:
            raise _CannotConvert(f"value {ast.unparse(value)}")
    return result


def _states_expression(states):
    values = [value.strip() for value in states.split(",") if value.strip()]
    if not values:
        raise _CannotConvert("empty states")
    if len(values) == 1:
        return f"state != {values[0]!r}"
    return f"state not in {tuple(values)!r}"


def _str2bool(value):
    value = value.strip().lower()
    if value in ("1", "true"):
        return True
    if value in ("0", "false"):
        return False
    raise _CannotConvert(f"non boolean static value {value!r}")


def _new_attributes(node):
    """[(name, value or None to remove)] replacing attrs / states on `node`."""
    expressions = {}
    if node.get("attrs") is not None:
        expressions.update(_attrs_to_expressions(node.get("attrs")))
    if node.get("states") is not None:
        states = _states_expression(node.get("states"))
        if "invisible" in expressions and expressions["invisible"] not in ("True", "False"):
            expressions["invisible"] = f"{expressions['invisible']} and {states}"
        else:
            expressions["invisible"] = states
    in_list = any(p.tag == "tree" for p in node.iterancestors()) and not any(
        p.tag == "header" for p in node.iterancestors()
    )
    changes = [("attrs", None), ("states", None)]
    for name, expression in expressions.items():
        static = node.get(name)
        if static is not None:
            if name == "invisible" and in_list:
                raise _CannotConvert("static invisible (column_invisible) in a list")
            if _str2bool(static):
                continue  # the static value wins
        changes.append((name, expression))
    return changes


def _quote_attribute(value):
    return '"%s"' % (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _edit_start_tag(tag_text, changes):
    """Start tag `tag_text` with the attributes changed in place."""
    attributes = list(_XML_ATTR_RE.finditer(tag_text))
    spans = {m["name"]: m for m in attributes}
    edits = []  # (start, end, text)
    pending = []
    anchor = spans.get("attrs") or spans.get("states")
    for name, value in changes:
        match = spans.get(name)
        if value is None:
            if match:
                edits.append((match.start(), match.end(), ""))
        elif match:
            edits.append((match.start("q"), match.end(), _quote_attribute(value)))
        else:
            pending.append(f"{anchor['sep']}{name}={_quote_attribute(value)}")
    if pending:
        position = anchor.end()
        edits.append((position, position, "".join(pending)))
    for start, end, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        tag_text = tag_text[:start] + text + tag_text[end:]
    return tag_text


def _escape_text(value):
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _move_attrs_to_attributes_view(logger, file_path: Path):
    """Replace attrs="{...}" and states="..." in the views by the 17.0 attributes
    (invisible="...", readonly="...", ...), in place: the rest of the file is kept
    as is. Nodes that cannot be converted safely are reported and kept."""
    content = file_path.read_bytes()
    if b"attrs" not in content and b"states" not in content:
        return
    try:
        tree = et.fromstring(content, et.XMLParser(remove_comments=False)).getroottree()
        text = content.decode("utf-8")
    except (et.XMLSyntaxError, UnicodeDecodeError):
        return
    # <template> too: QWeb views are not validated, but some are view fragments
    # (OCA/server-ux 17.0 base_cancel_confirm/views/cancel_confirm_template.xml)
    archs = tree.xpath(f"{_ARCH_XPATH} | data/{_ARCH_XPATH} | template | data/template")
    if not archs:
        return
    in_arch = set()
    for arch in archs:
        in_arch.update(arch.iterdescendants())
    elements = [e for e in tree.getroot().iter() if isinstance(e.tag, str)]
    masked = _MASK_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), text)
    tags = list(_START_TAG_RE.finditer(masked))
    if len(tags) != len(elements) or any(
        m["tag"] != et.QName(e).localname and m["tag"] != e.tag for m, e in zip(tags, elements)
    ):
        logger.warning(
            "%s: attrs/states not converted (XML layout not understood), convert them by hand",
            file_path.name,
        )
        return
    edits = []  # (start, end, new text)
    for match, node in zip(tags, elements):
        if node not in in_arch:
            continue
        try:
            if "attrs" in node.attrib or "states" in node.attrib:
                changes = _new_attributes(node)
                new_tag = _edit_start_tag(match.group(), changes)
                edits.append((match.start(), match.end(), new_tag))
            elif node.tag == "attribute" and node.get("name") in ("attrs", "states"):
                if len(node) or match.group().endswith("/>"):
                    raise _CannotConvert("empty or structured <attribute>")
                end = masked.index("</attribute>", match.end()) + len("</attribute>")
                value = node.text or ""
                if node.get("name") == "attrs":
                    expressions = _attrs_to_expressions(value) if value.strip() else {}
                else:
                    expressions = {"invisible": _states_expression(value)}
                if not expressions:
                    raise _CannotConvert("empty <attribute>")
                line_start = masked.rfind("\n", 0, match.start()) + 1
                indent = masked[line_start:match.start()]
                if indent.strip():
                    indent = ""
                opening = _XML_ATTR_RE.sub(
                    lambda m: m.group() if m["name"] != "name" else f'{m["sep"]}name="{{name}}"',
                    match.group(),
                )
                new_nodes = [
                    opening.replace("{name}", name) + _escape_text(expression) + "</attribute>"
                    for name, expression in expressions.items()
                ]
                edits.append((match.start(), end, ("\n" + indent).join(new_nodes)))
        except _CannotConvert as error:
            logger.warning(
                "%s line %s: attrs/states of <%s> not converted (%s), convert it by hand",
                file_path.name, node.sourceline, node.tag, error,
            )
    if not edits:
        return
    for start, end, new_text in sorted(edits, reverse=True):
        text = text[:start] + new_text + text[end:]
    file_path.write_text(text, encoding="utf-8")


def _check_open_form(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    reformat_file_ext = ".xml"
    file_paths = _get_files(module_path, reformat_file_ext)
    logger.debug(f"{reformat_file_ext} files found:\n" f"{list(map(str, file_paths))}")

    for file_path in file_paths:
        _check_open_form_view(logger, file_path)


def _move_attrs_to_attributes(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    reformat_file_ext = ".xml"
    file_paths = _get_files(module_path, reformat_file_ext)
    logger.debug(f"{reformat_file_ext} files found:\n" f"{list(map(str, file_paths))}")

    for file_path in file_paths:
        _move_attrs_to_attributes_view(logger, file_path)


def _reformat_read_group(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    """Reformat read_group method in py files."""

    reformat_file_ext = ".py"
    file_paths = _get_files(module_path, reformat_file_ext)
    logger.debug(f"{reformat_file_ext} files found:\n" f"{list(map(str, file_paths))}")

    reformatted_files = list()
    for file_path in file_paths:
        reformatted_file = replace_read_group_signature(logger, file_path)
        if reformatted_file:
            reformatted_files.append(reformatted_file)
    logger.debug("Reformatted files:\n" f"{list(reformatted_files)}")


class MigrationScript(BaseMigrationScript):

    _GLOBAL_FUNCTIONS = [
        _check_open_form,
        _reformat_read_group,
        _move_attrs_to_attributes,
    ]
