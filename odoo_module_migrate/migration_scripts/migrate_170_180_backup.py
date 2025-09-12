# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
# This script is based on the original code from:
# https://github.com/odoo/odoo/blob/master/odoo/upgrade_code/17.5-00-tree-to-list.py

from odoo_module_migrate.base_migration_script import BaseMigrationScript
import re


def replace_tree_with_list_in_views(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    files_to_process = tools.get_files(module_path, (".xml", ".js", ".py"))

    reg_tree_to_list_xml_mode = re.compile(
        r"""(<field[^>]* name=["'](view_mode|name|binding_view_types)["'][^>]*>([^<>]+[,.])?\s*)tree(\s*([,.][^<>]+)?</field>)"""
    )
    reg_tree_to_list_tag = re.compile(r"([<,/])tree([ \n\r,>/])")
    reg_tree_to_list_xpath = re.compile(
        r"""(<xpath[^>]* expr=['"])([^<>]*/)?tree(/|[\['"])"""
    )
    reg_tree_to_list_ref = re.compile(r"tree_view_ref")
    reg_tree_to_list_mode = re.compile(r"""(mode=['"][^'"]*)tree([^'"]*['"])""")
    reg_tree_to_list_view_mode = re.compile(
        r"""(['"]view_mode['"][^'":=]*[:=].*['"]([^'"]+,)?\s*)tree(\s*(,[^'"]+)?['"])"""
    )
    reg_tree_to_list_view = re.compile(
        r"""(['"]views['"][^'":]*[:=].*['"])tree(['"])"""
    )
    reg_tree_to_list_string = re.compile(r"""([ '">)])tree( [vV]iews?[ '"<.)])""")
    reg_tree_to_list_String = re.compile(r"""([ '">)])Tree( [vV]iews?[ '"<.)])""")
    reg_tree_to_list_env_ref = re.compile(r"""(self\.env\.ref\(.*['"])tree(['"])""")

    for file in files_to_process:
        try:
            content = tools._read_content(file)
            content = content.replace(" tree view ", " list view ")
            content = reg_tree_to_list_xml_mode.sub(r"\1list\4", content)
            content = reg_tree_to_list_tag.sub(r"\1list\2", content)
            content = reg_tree_to_list_xpath.sub(r"\1\2list\3", content)
            content = reg_tree_to_list_ref.sub("list_view_ref", content)
            content = reg_tree_to_list_mode.sub(r"\1list\2", content)
            content = reg_tree_to_list_view_mode.sub(r"\1list\3", content)
            content = reg_tree_to_list_view.sub(r"\1list\2", content)
            content = reg_tree_to_list_string.sub(r"\1list\2", content)
            content = reg_tree_to_list_String.sub(r"\1List\2", content)
            content = reg_tree_to_list_env_ref.sub(r"\1list\2", content)

            tools._write_content(file, content)

        except Exception as e:
            logger.error(f"Error processing file {file}: {str(e)}")


def replace_chatter_blocks(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    files_to_process = tools.get_files(module_path, (".xml",))

    reg_chatter_block = r"""<div class=["']oe_chatter["'](?![^>]*position=["'][^"']+["'])[^>]*>[\s\S]*?</div>"""
    reg_xpath_chatter = r"""//div\[hasclass\(['"]oe_chatter['"]\)\]"""
    reg_chatter_with_position_self_closing = (
        r"""<div class=["']oe_chatter["']\s*(position=["'][^"']+["'])\s*/>"""
    )

    replacement_div = "<chatter/>"
    replacement_xpath = "//chatter"

    def replace_chatter_self_closing(match):
        position = match.group(1)
        return f"<chatter {position}/>"

    replaces = {
        reg_chatter_block: replacement_div,
        reg_xpath_chatter: replacement_xpath,
        reg_chatter_with_position_self_closing: replace_chatter_self_closing,
    }

    for file in files_to_process:
        try:
            tools._replace_in_file(
                file, replaces, log_message=f"Updated chatter blocks in file: {file}"
            )
        except Exception as e:
            logger.error(f"Error processing file {file}: {str(e)}")


def replace_deprecated_kanban_box_card_menu(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    files_to_process = tools.get_files(module_path, (".xml", ".js", ".py"))
    replaces = {
        "kanban-card": "card",
        "kanban-box": "card",
        "kanban-menu": "menu",
    }
    for file in files_to_process:
        try:
            tools._replace_in_file(
                file,
                replaces,
                log_message=f"""Replace kanban-card and kanban-box with card, also change kanban-menu with menu" in file: {file}""",
            )
        except Exception as e:
            logger.error(f"Error processing file {file}: {str(e)}")


def replace_user_has_groups(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    files_to_process = tools.get_files(module_path, (".py",))
    replaces = {
        r"self\.user_has_groups\(\s*(['\"])([\w\.]+)\1\s*\)": r"self.env.user.has_group(\1\2\1)",
        r"self\.user_has_groups\(\s*(['\"])([^'\"]*[,!][^'\"]*?)\1\s*\)": r"self.env.user.has_groups(\1\2\1)",
    }

    for file in files_to_process:
        try:
            tools._replace_in_file(file, replaces)
        except Exception as e:
            logger.error(f"Error processing file {file}: {str(e)}")


def replace_unaccent_parameter(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    files_to_process = tools.get_files(module_path, (".py",))
    replaces = {
        # Handle multiline with unaccent=False or unaccent=True
        r"(?s)fields\.(Char|Text|Html|Properties)\(\s*unaccent\s*=\s*(False|True)\s*,?\s*\)": r"fields.\1()",
        # Handle when unaccent=False or unaccent=True is the first parameter
        r"(?s)fields\.(Char|Text|Html|Properties)\(\s*unaccent\s*=\s*(False|True)\s*,\s*([^)]+?)\)": r"fields.\1(\3)",
        # Handle when unaccent=False or unaccent=True is between other parameters
        r"(?s)fields\.(Char|Text|Html|Properties)\(([^)]+?),\s*unaccent\s*=\s*(False|True)\s*,\s*([^)]+?)\)": r"fields.\1(\2, \4)",
        # Handle when unaccent=False or unaccent=True is the last parameter
        r"(?s)fields\.(Char|Text|Html|Properties)\(([^)]+?),\s*unaccent\s*=\s*(False|True)\s*\)": r"fields.\1(\2)",
    }

    for file in files_to_process:
        try:
            tools._replace_in_file(
                file,
                replaces,
                log_message=f"[18.0] Removed deprecated unaccent=False parameter in file: {file}",
            )
        except Exception as e:
            logger.error(f"Error processing file {file}: {str(e)}")


def replace_ustr(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    files_to_process = tools.get_files(module_path, (".py",))
    replaces = {
        r"from\s+odoo\.tools\s+import\s+ustr\s*\n": "",
        r"from\s+odoo\.tools\.misc\s+import\s+ustr\s*\n": "",
        r"from\s+odoo\.tools\s+import\s+([^,\n]*,\s*)?ustr,\s*([^,\n]*)": r"from odoo.tools import \1\2",
        r"from\s+odoo\.tools\.misc\s+import\s+([^,\n]*,\s*)?ustr,\s*([^,\n]*)": r"from odoo.tools.misc import \1\2",
        r",\s*ustr(\s*,)?": r"\1",
        r"tools\.ustr\(([^)]+)\)": r"\1",
        r"misc\.ustr\(([^)]+)\)": r"\1",
        r"=\s*ustr\(([^)]+)\)": r"= \1",
    }
    for file in files_to_process:
        try:
            tools._replace_in_file(
                file, replaces, log_message=f"Deprecate ustr in: {file}"
            )
        except Exception as e:
            logger.error(f"Error processing file {file}: {str(e)}")


def replace_attrs_and_states(
    logger, module_path, module_name, manifest_path, migration_steps, tools
):
    """Replace deprecated attrs and states attributes with direct modifiers for Odoo 17.0+.
    Uses text-based replacement to preserve original formatting and indentation."""
    import re
    import ast
    from pathlib import Path
    
    files_to_process = tools.get_files(module_path, (".xml",))
    
    def convert_condition_to_expression(condition):
        """Convert a single Odoo domain condition to Python expression."""
        if not isinstance(condition, (list, tuple)) or len(condition) != 3:
            return str(condition)
            
        field, operator, value = condition
        
        # Handle different value types
        if value is False:
            if operator == '=':
                return f"not {field}"
            elif operator == '!=':
                return field
            else:
                return f"{field} {operator} False"
        elif value is True:
            if operator == '=':
                return field
            elif operator == '!=':
                return f"not {field}"
            else:
                return f"{field} {operator} True"
        elif isinstance(value, str):
            if operator == '=':
                return f"{field} == '{value}'"
            elif operator == '!=':
                return f"{field} != '{value}'"
            elif operator == 'in':
                return f"{field} in ('{value}')"
            elif operator == 'not in':
                return f"{field} not in ('{value}')"
            else:
                return f"{field} {operator} '{value}'"
        elif isinstance(value, (int, float)):
            if operator == '=':
                return f"{field} == {value}"
            elif operator == '!=':
                return f"{field} != {value}"
            else:
                return f"{field} {operator} {value}"
        elif isinstance(value, (list, tuple)):
            # Handle list/tuple values like ('draft', 'done')
            value_str = ', '.join([f"'{v}'" if isinstance(v, str) else str(v) for v in value])
            if operator == 'in':
                return f"{field} in ({value_str})"
            elif operator == 'not in':
                return f"{field} not in ({value_str})"
            else:
                return f"{field} {operator} ({value_str})"
        else:
            return f"{field} {operator} {value}"
    
    def convert_conditions_to_expression(conditions):
        """Convert a list of Odoo domain conditions to Python expression."""
        if not isinstance(conditions, list):
            if conditions == 1 or conditions is True:
                return "True"
            elif conditions == 0 or conditions is False:
                return "False"
            return str(conditions)
        
        # Handle simple case with just conditions (no logical operators)
        if len(conditions) > 0 and all(isinstance(item, (list, tuple)) and len(item) == 3 for item in conditions):
            # All items are simple conditions, default to AND
            expressions = [convert_condition_to_expression(item) for item in conditions]
            if len(expressions) == 1:
                return expressions[0]
            else:
                return " and ".join(f"({expr})" for expr in expressions)
        
        # Handle complex cases with logical operators
        expressions = []
        logical_operator = 'and'  # Default
        i = 0
        
        while i < len(conditions):
            item = conditions[i]
            if isinstance(item, str) and item in ['&', '|', '!']:
                if item == '|':
                    logical_operator = 'or'
                elif item == '&':
                    logical_operator = 'and'
                elif item == '!':
                    # NOT operator - apply to next condition
                    i += 1
                    if i < len(conditions):
                        next_expr = convert_condition_to_expression(conditions[i])
                        expressions.append(f"not ({next_expr})")
                i += 1
                continue
            else:
                expr = convert_condition_to_expression(item)
                expressions.append(expr)
                i += 1
        
        if len(expressions) == 1:
            return expressions[0]
        elif len(expressions) > 1:
            return f" {logical_operator} ".join(f"({expr})" for expr in expressions)
        else:
            return "True"
    
    def process_attrs_replacement(match):
        """Process a single attrs attribute match and convert it."""
        full_match = match.group(0)
        attrs_content = match.group(1)
        
        try:
            # Parse the attrs dictionary
            attrs_dict = ast.literal_eval(attrs_content)
            
            if not isinstance(attrs_dict, dict):
                logger.warning(f"attrs is not a dict: {attrs_content}")
                return full_match
            
            # Convert each modifier
            replacements = []
            for modifier, conditions in attrs_dict.items():
                if modifier in ['invisible', 'readonly', 'required']:
                    expression = convert_conditions_to_expression(conditions)
                    replacements.append(f'{modifier}="{expression}"')
                    logger.debug(f"Converted {modifier}: {conditions} -> {expression}")
            
            # Return the replacement attributes
            if replacements:
                return ' '.join(replacements)
            else:
                return ''
                
        except (ValueError, SyntaxError, TypeError) as e:
            logger.warning(f"Could not parse attrs: {attrs_content}, error: {e}")
            return f'_attrs_conversion_error="{attrs_content}"'
    
    def process_states_replacement(match):
        """Process a single states attribute match and convert it."""
        states_content = match.group(1)
        
        try:
            # Convert states="draft,done" to invisible="state not in ('draft','done')"
            states_list = [s.strip() for s in states_content.split(',')]
            if len(states_list) == 1:
                expression = f"state != '{states_list[0]}'"
            else:
                states_str = "', '".join(states_list)
                expression = f"state not in ('{states_str}')"
            
            logger.debug(f"Converted states: {states_content} -> invisible=\"{expression}\"")
            return f'invisible="{expression}"'
            
        except Exception as e:
            logger.warning(f"Could not parse states: {states_content}, error: {e}")
            return f'_states_conversion_error="{states_content}"'
    
    for file in files_to_process:
        try:
            if not Path(file).exists():
                continue
            
            # Read the file content
            with open(file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Replace attrs patterns
            # Match attrs="..." or attrs='...' with proper JSON dict parsing
            def find_and_replace_attrs(content):
                result = content
                # Find all attrs= patterns and process them
                pattern = r'attrs\s*=\s*(["\'])({.*?})\1'
                matches = list(re.finditer(pattern, content, re.DOTALL))
                
                # Process matches in reverse order to avoid position shifts
                for match in reversed(matches):
                    full_match = match.group(0)
                    quote_type = match.group(1)
                    attrs_content = match.group(2)
                    
                    try:
                        # Parse and convert
                        attrs_dict = ast.literal_eval(attrs_content)
                        if isinstance(attrs_dict, dict):
                            replacements = []
                            for modifier, conditions in attrs_dict.items():
                                if modifier in ['invisible', 'readonly', 'required']:
                                    expression = convert_conditions_to_expression(conditions)
                                    replacements.append(f'{modifier}="{expression}"')
                                    logger.debug(f"Converted {modifier}: {conditions} -> {expression}")
                            
                            if replacements:
                                replacement = ' '.join(replacements)
                            else:
                                replacement = ''
                            
                            # Replace in result
                            result = result[:match.start()] + replacement + result[match.end():]
                            
                    except (ValueError, SyntaxError, TypeError) as e:
                        logger.warning(f"Could not parse attrs: {attrs_content}, error: {e}")
                        replacement = f'_attrs_conversion_error="{attrs_content}"'
                        result = result[:match.start()] + replacement + result[match.end():]
                
                return result
            
            content = find_and_replace_attrs(content)
            
            # Replace states patterns  
            states_pattern = r'states\s*=\s*["\']([^"\']*)["\']'
            content = re.sub(states_pattern, process_states_replacement, content)
            
            # Handle invisible to column_invisible in tree/list views
            # Find tree or list view sections and replace invisible with column_invisible in fields
            def replace_invisible_in_tree(match):
                view_content = match.group(0)
                # Replace invisible with column_invisible only in field elements
                field_invisible_pattern = r'(<field[^>]*?\s)invisible(\s*=\s*["\'][^"\']*["\'])'
                view_content = re.sub(field_invisible_pattern, r'\1column_invisible\2', view_content)
                return view_content
            
            # Find tree/list sections and process them
            tree_pattern = r'<(tree|list)[^>]*>.*?</\1>'
            content = re.sub(tree_pattern, replace_invisible_in_tree, content, flags=re.DOTALL)
            
            # Write the modified content if changes were made
            if content != original_content:
                with open(file, 'w', encoding='utf-8') as f:
                    f.write(content)
                logger.info(f"Updated attrs/states in file: {file}")
            
        except Exception as e:
            logger.error(f"Error processing file {file}: {str(e)}")


class MigrationScript(BaseMigrationScript):
    _GLOBAL_FUNCTIONS = [
        replace_unaccent_parameter,
        replace_deprecated_kanban_box_card_menu,
        replace_tree_with_list_in_views,
        replace_chatter_blocks,
        replace_user_has_groups,
        replace_ustr,
        replace_attrs_and_states,
    ]
