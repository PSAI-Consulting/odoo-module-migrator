# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import ast
import json
import re

from odoo_module_migrate.base_migration_script import BaseMigrationScript


IMPORT_EXPRESSION_RE = re.compile(r"^([ \t]*)from odoo\.osv import expression[ \t]*$", re.M)
IMPORT_AND_OR_RE = re.compile(
    r"^([ \t]*)from odoo\.osv\.expression import \(?[ \t]*(AND|OR)[ \t]*(?:,[ \t]*(AND|OR)[ \t]*)?,?[ \t]*\)?[ \t]*$",
    re.M
)


def _code_names(text):
    """(start offset, name, previous significant token, next token) of the
    NAME tokens of Python code (strings and comments excluded)."""
    import io
    import tokenize

    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    result = []
    tokens = [
        t for t in tokenize.generate_tokens(io.StringIO(text).readline)
        if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT)
    ]
    for index, token in enumerate(tokens):
        if token.type == tokenize.NAME:
            previous = tokens[index - 1].string if index else ""
            following = tokens[index + 1].string if index + 1 < len(tokens) else ""
            following2 = tokens[index + 2].string if index + 2 < len(tokens) else ""
            following3 = tokens[index + 3].string if index + 3 < len(tokens) else ""
            offset = starts[token.start[0] - 1] + token.start[1]
            result.append((offset, token.string, previous, following, following2, following3))
    return result


def convert_expression_to_domain(text):
    """odoo.osv.expression AND / OR -> odoo.fields.Domain.AND / OR (odoo.osv
    was removed in 20.0). Only done when every use of the import is a call of
    AND / OR: other functions (normalize_domain, TRUE_DOMAIN...) have no
    direct equivalent and are left (reported by the 20.0 rules)."""
    try:
        names = _code_names(text)
    except Exception:  # noqa: BLE001 - tokenize errors: left as is
        return text
    edits = []  # (start, end, replacement)
    module_import = IMPORT_EXPRESSION_RE.search(text)
    if module_import:
        uses = [n for n in names if n[1] == "expression" and n[2] != "." and n[0] > module_import.end()]
        if uses and all(n[3] == "." and n[4] in ("AND", "OR") and n[5] == "(" for n in uses):
            for offset, *_ in uses:
                edits.append((offset, offset + len("expression"), "Domain"))
            edits.append((module_import.start(), module_import.end(),
                          f"{module_import.group(1)}from odoo.fields import Domain"))
    names_import = IMPORT_AND_OR_RE.search(text)
    if names_import:
        imported = {names_import.group(2), names_import.group(3)} - {None}
        uses = [n for n in names if n[1] in imported and n[2] != "."
                and n[0] > names_import.end()]
        if uses and all(n[3] == "(" for n in uses):
            for offset, name, *_ in uses:
                edits.append((offset, offset + len(name), f"Domain.{name}"))
            edits.append((names_import.start(), names_import.end(),
                          f"{names_import.group(1)}from odoo.fields import Domain"))
    if not edits:
        return text
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    # one import of Domain is enough
    seen = False
    lines = []
    for line in text.split("\n"):
        if line.strip() == "from odoo.fields import Domain":
            if seen:
                continue
            seen = True
        lines.append(line)
    return "\n".join(lines)


def migrate_expression_to_domain(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    """Convert odoo.osv.expression AND / OR to odoo.fields.Domain"""
    for file in tools.get_files(module_path, (".py",)):
        content = tools._read_content(file)
        if "odoo.osv" not in content:
            continue
        new_content = convert_expression_to_domain(content)
        if new_content != content:
            tools._write_content(file, new_content)
            logger.info(f"Migrated expression imports to Domain in: {file}")


def upgrade_sql_constraints(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    # Odoo method in which we migrate all occurrences of _sql_constraints
    if tools.RUN_CONTEXT.get("upgrade_code"):
        # Odoo's official 18.1-00-sql-constraint.py (ast based) will do it
        return
    files_to_process = tools.get_files(module_path, (".py",))
    # Regex pattern explanation:
    # (?m) - Multiline mode, ^ matches start of each line
    # ^(?![ \t]*#) - Negative lookahead: exclude lines starting with # (comments)
    # ([ \t]*) - Capture group 1: leading spaces/tabs (NOT newlines to avoid extra blank lines)
    # \b_sql_constraints\s*=\s*\[ - Match "_sql_constraints = ["
    # ([^\]]+) - Capture group 2: constraint content (everything until the closing bracket)
    # ] - Match closing bracket
    # re.DOTALL - Allow . to match newlines for multi-line constraints
    sql_expression_re = re.compile(
        r"(?m)^(?![ \t]*#)([ \t]*)\b_sql_constraints\s*=\s*\[([^\]]+)]", re.DOTALL
    )
    ind = " " * 4

    # Function to build the new SQL constraint definition
    def build_sql_object(match):
        # Preserve the original indentation level (e.g., 2 spaces, 4 spaces, 8 spaces for nested classes)
        leading_indent = match.group(1)
        try:
            constraints = ast.literal_eval("[" + match.group(2) + "]")
        except (ValueError, SyntaxError):
            # e.g. messages built with _("..."): left as is, reported below
            return match.group(0)
        result = []
        for name, definition, *messages in constraints:
            message = messages[0] if messages else ""
            constructor = "Constraint"
            if message:
                # format on 2 lines
                message_repr = json.dumps(
                    message, ensure_ascii=False
                )  # so that the message is in double quotes
                args = f"\n{ind * 2}{definition!r},\n{ind * 2}{message_repr},\n{ind}"
            elif len(definition) > 60:
                args = f"\n{ind * 2}{definition!r}"
            else:
                args = repr(definition)
            result.append(f"{leading_indent}_{name} = models.{constructor}({args})")
        return "\n".join(result)

    # Process each file
    for file in files_to_process:
        content = tools._read_content(file)
        content = sql_expression_re.sub(build_sql_object, content)
        if sql_expression_re.search(content):
            logger.warning(
                "[19] _sql_constraints not converted to models.Constraint (give --odoo-root"
                " to use Odoo's 18.1-00-sql-constraint.py). File %s" % file
            )
        tools._write_content(file, content)


# Tokens of an XML text: comments, <search> start / end tags, <group> start tags
# (attribute values may contain '>')
_ATTRS = r"""(?:[^>"']|"[^"]*"|'[^']*')*"""
SEARCH_TOKEN_RE = re.compile(
    rf"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<search\b{_ATTRS}>|</search\s*>|<group\b{_ATTRS}>",
    re.S,
)
GROUP_ATTR_RE = re.compile(r"""\s+(?:expand|string)\s*=\s*(?:"[^"]*"|'[^']*')""")


def remove_search_group_attrs(text):
    """Text without the `expand` / `string` attributes of the <group> of
    <search> views; the rest of the file is left as is."""
    depth = 0
    parts, last = [], 0
    for match in SEARCH_TOKEN_RE.finditer(text):
        token = match.group(0)
        if token.startswith(("<!--", "<![CDATA[")):
            continue
        if token.startswith("</search"):
            depth = max(depth - 1, 0)
        elif token.startswith("<search"):
            if not token.endswith("/>"):
                depth += 1
        elif depth:
            new_token = GROUP_ATTR_RE.sub("", token)
            if new_token != token:
                parts.append(text[last:match.start()])
                parts.append(new_token)
                last = match.end()
    if not parts:
        return text
    parts.append(text[last:])
    return "".join(parts)


def _remove_group_attrs_in_search_views(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    """Remove the `expand` and `string` attributes of the <group> of search
    views: not allowed anymore by odoo/addons/base/rng/common.rng in 19.0.

    The attributes are removed from the text (the file is not serialized
    again: formatting, entities and comments are kept).
    """
    for file_path in tools.get_files(module_path, (".xml",)):
        content = tools._read_content(file_path)
        if "<search" not in content:
            continue
        new_content = remove_search_group_attrs(content)
        if new_content != content:
            tools._write_content(file_path, new_content)
            logger.info(
                f"Removed expand/string attrs from <group> in search views: {file_path}"
            )


class MigrationScript(BaseMigrationScript):
    _GLOBAL_FUNCTIONS = [
        upgrade_sql_constraints,
        migrate_expression_to_domain,
        _remove_group_attrs_in_search_views,
    ]
