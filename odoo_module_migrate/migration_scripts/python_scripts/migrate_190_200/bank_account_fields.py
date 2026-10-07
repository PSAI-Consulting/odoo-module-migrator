"""Odoo 20 bank account field names in model-aware and bank-specific contexts.

Source: odoo 113d77eb35aa ``[IMP] *: Improve UX of bank accounts``.
The generic field engine handles ``env['res.partner.bank']`` and known views.
This script covers contexts whose model cannot be inferred from Python/XML
alone: QWeb variables named after a bank and nested create commands of the
``bank_ids`` relation. External payload keys named ``acc_number`` stay intact.
"""

import ast
import re

from odoo_module_migrate.analysis import fields


BANK_RECEIVER_RE = re.compile(r"(?:^|_)(?:bank|banks)(?:_|$)", re.I)
QWEB_ATTRIBUTES = ("t-field", "t-esc", "t-if", "t-elif", "t-value", "t-out")


def _receiver_name(node):
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        if isinstance(node, ast.Attribute):
            name = node.attr
            node = node.value
            if BANK_RECEIVER_RE.search(name):
                return name
        elif isinstance(node, ast.Subscript):
            node = node.value
        else:
            node = node.func
    return node.id if isinstance(node, ast.Name) else ""


def _dict_value(mapping, name):
    for key, value in zip(mapping.keys, mapping.values):
        if isinstance(key, ast.Constant) and key.value == name:
            return value


def _bank_command_keys(node):
    """Yield ``'acc_number'`` constants below a ``'bank_ids'`` dict value."""
    for mapping in ast.walk(node):
        if not isinstance(mapping, ast.Dict):
            continue
        commands = _dict_value(mapping, "bank_ids")
        if commands is None:
            continue
        for nested in ast.walk(commands):
            if not isinstance(nested, ast.Dict):
                continue
            for key in nested.keys:
                if isinstance(key, ast.Constant) and key.value == "acc_number":
                    yield key


def _python_edits(text):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}, []
    positions = fields._Positions(text)
    edits, unresolved = {}, []
    usages, _defined = fields.python_usages(text)
    for usage in usages:
        if usage.model == "res.partner.bank" and usage.field == "acc_number":
            edits[usage.start, usage.end] = "account_number"
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "acc_number":
            end = positions.offset(node.end_lineno, node.end_col_offset)
            span = (end - len(node.attr), end)
            if BANK_RECEIVER_RE.search(_receiver_name(node.value)):
                edits[span] = "account_number"
            elif span not in edits:
                unresolved.append(node.lineno)
    for key in _bank_command_keys(tree):
        start = positions.offset(key.lineno, key.col_offset)
        end = positions.offset(key.end_lineno, key.end_col_offset)
        raw = text[start:end]
        relative = raw.find("acc_number")
        if relative >= 0:
            edits[start + relative, start + relative + len("acc_number")] = (
                "account_number"
            )
    return edits, unresolved


def _qweb(text):
    changed = 0

    def tag(match):
        nonlocal changed
        value = match[0]
        if value.startswith("<!--"):
            return value
        for attribute in QWEB_ATTRIBUTES:
            pattern = re.compile(
                rf"(\b{re.escape(attribute)}\s*=\s*(['\"]))(.*?)(\2)", re.S
            )

            def expression(found):
                nonlocal changed
                expression_text = found.group(3)

                def field_name(field_match):
                    nonlocal changed
                    receiver = field_match.group(1).split(".")[-1]
                    if not BANK_RECEIVER_RE.search(receiver):
                        return field_match[0]
                    changed += 1
                    return field_match.group(1) + ".account_number"

                expression_text = re.sub(
                    r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\.acc_number\b",
                    field_name,
                    expression_text,
                )
                return found.group(1) + expression_text + found.group(4)

            value = pattern.sub(expression, value)
        return value

    result = re.sub(
        r'<!--[\s\S]*?-->|<[^>"\']*(?:"[^"]*"|\'[^\']*\'|[^>"\']*)*>',
        tag,
        text,
    )
    unresolved = []
    attribute_names = "|".join(map(re.escape, QWEB_ATTRIBUTES))
    for match in re.finditer(
        rf"\b(?:{attribute_names})\s*=\s*(['\"])(.*?)\1", result, re.S
    ):
        if re.search(r"\.acc_number\b", match.group(2)):
            unresolved.append(result.count("\n", 0, match.start()) + 1)
    return result, changed, unresolved


def migrate_bank_account_fields(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py", ".xml")):
        text = tools._read_content(path)
        if "acc_number" not in text:
            continue
        if path.suffix == ".py":
            edits, unresolved = _python_edits(text)
            new = text
            for (start, end), replacement in sorted(edits.items(), reverse=True):
                new = new[:start] + replacement + new[end:]
            for line in sorted(set(unresolved)):
                logger.error(
                    "[20] Ambiguous .acc_number access: res.partner.bank renamed it to"
                    " account_number; resolve the receiver model. File %s:%s",
                    path,
                    line,
                )
        else:
            new, _count, unresolved = _qweb(text)
            for line in sorted(set(unresolved)):
                logger.error(
                    "[20] Ambiguous .acc_number in QWeb: res.partner.bank renamed it"
                    " to account_number; resolve the expression model. File %s:%s",
                    path,
                    line,
                )
        if new != text:
            tools._write_content(path, new)
            logger.info(
                "[20] Renamed res.partner.bank.acc_number to account_number"
                " (odoo 113d77eb35aa). File %s",
                path,
            )
