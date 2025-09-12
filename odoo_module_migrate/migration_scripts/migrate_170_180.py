# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo_module_migrate.base_migration_script import BaseMigrationScript
import re
import ast
from pathlib import Path


def replace_tree_with_list_in_views(logger, module_path, module_name, manifest_path, migration_steps, tools):
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
            original_content = content
            
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

            if content != original_content:
                tools._write_content(file, content)
                logger.info(f"Updated tree->list in: {file}")

        except Exception as e:
            logger.error(f"Error processing file {file}: {str(e)}")


def replace_attrs_and_states(logger, module_path, module_name, manifest_path, migration_steps, tools):
    """Replace deprecated 'attrs' and 'states' attributes with individual attributes."""
    
    xml_files = []
    for subdir in ['views', 'data', 'demo', 'security', 'wizard']:
        xml_dir = Path(module_path) / subdir
        if xml_dir.exists():
            xml_files.extend(xml_dir.glob('**/*.xml'))
    xml_files.extend(Path(module_path).glob('*.xml'))
    
    if not xml_files:
        logger.debug(f"No XML files found in {module_name}")
        return
    
    logger.info(f"Processing {len(xml_files)} XML files for attrs/states migration in {module_name}")
    
    def convert_domain_to_expression(domain):
        if not domain or not isinstance(domain, list):
            return "True"
        
        def convert_condition(condition):
            if not isinstance(condition, (list, tuple)) or len(condition) != 3:
                return "True"
            field, operator, value = condition
            
            if operator == '=':
                if isinstance(value, bool):
                    return f"{field}" if value else f"not {field}"
                elif isinstance(value, (int, float)):
                    return f"{field} == {value}"
                else:
                    return f"{field} == '{value}'"
            elif operator == '!=':
                if isinstance(value, bool):
                    return f"not {field}" if value else f"{field}"
                elif isinstance(value, (int, float)):
                    return f"{field} != {value}"
                else:
                    return f"{field} != '{value}'"
            elif operator == 'in':
                if isinstance(value, list):
                    if all(isinstance(v, str) for v in value):
                        values = "', '".join(value)
                        return f"{field} in ('{values}')"
                    else:
                        return f"{field} in {value}"
                return f"{field} in {value}"
            elif operator == 'not in':
                if isinstance(value, list):
                    if all(isinstance(v, str) for v in value):
                        values = "', '".join(value)
                        return f"{field} not in ('{values}')"
                    else:
                        return f"{field} not in {value}"
                return f"{field} not in {value}"
            elif operator in ['>', '>=', '<', '<=']:
                return f"{field} {operator} {value}"
            else:
                return f"{field} {operator} {value}"
        
        # Handle logical operators
        result_parts = []
        i = 0
        current_operator = 'and'
        
        while i < len(domain):
            item = domain[i]
            
            if item in ['&', '|', '!']:
                if item == '&':
                    current_operator = 'and'
                elif item == '|':
                    current_operator = 'or'
                elif item == '!':
                    # Negation - apply to next condition
                    i += 1
                    if i < len(domain):
                        next_condition = convert_condition(domain[i])
                        result_parts.append(f"not ({next_condition})")
                    i += 1
                    continue
            else:
                condition_expr = convert_condition(item)
                result_parts.append(condition_expr)
            
            i += 1
        
        # Join with the current operator
        if len(result_parts) == 1:
            return result_parts[0]
        elif current_operator == 'or':
            return ' or '.join([f"({part})" for part in result_parts])
        else:  # and
            return ' and '.join([f"({part})" for part in result_parts])
    
    def process_single_file(file_path):
        """Process a single XML file for attrs and states migration."""
        try:
            # Read file content
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            modifications_made = False
            
            # 1. Handle <attribute name="attrs">...</attribute> in xpath
            xpath_attrs_pattern = r'<attribute\s+name=["\']attrs["\']>\s*({.*?})\s*</attribute>'
            def replace_xpath_attrs(match):
                nonlocal modifications_made
                attrs_content = match.group(1)
                try:
                    attrs_dict = ast.literal_eval(attrs_content)
                    if isinstance(attrs_dict, dict):
                        replacements = []
                        for modifier, conditions in attrs_dict.items():
                            if modifier in ['invisible', 'readonly', 'required', 'column_invisible']:
                                expression = convert_domain_to_expression(conditions)
                                replacements.append(f'<attribute name="{modifier}">{expression}</attribute>')
                        
                        if replacements:
                            modifications_made = True
                            logger.debug(f"Converted xpath attrs in {file_path}: {attrs_content}")
                            return '\n            '.join(replacements)
                
                except Exception as e:
                    logger.warning(f"Could not parse xpath attrs in {file_path}: {attrs_content}, error: {e}")
                
                return match.group(0)  # Return unchanged if parsing fails
            
            content = re.sub(xpath_attrs_pattern, replace_xpath_attrs, content, flags=re.DOTALL)
            
            # 2. Handle attrs="..." attributes
            attrs_pattern = r'attrs\s*=\s*["\']({.*?})["\']'
            def replace_attrs(match):
                nonlocal modifications_made
                attrs_content = match.group(1)
                try:
                    attrs_dict = ast.literal_eval(attrs_content)
                    if isinstance(attrs_dict, dict):
                        replacements = []
                        for modifier, conditions in attrs_dict.items():
                            if modifier in ['invisible', 'readonly', 'required', 'column_invisible']:
                                expression = convert_domain_to_expression(conditions)
                                replacements.append(f'{modifier}="{expression}"')
                        
                        if replacements:
                            modifications_made = True
                            logger.debug(f"Converted attrs in {file_path}: {attrs_content}")
                            return ' '.join(replacements)
                        else:
                            modifications_made = True
                            return ''  # Remove empty attrs
                
                except Exception as e:
                    logger.warning(f"Could not parse attrs in {file_path}: {attrs_content}, error: {e}")
                    return f'_attrs_migration_error="{attrs_content}"'
                
                return match.group(0)  # Return unchanged if no valid modifiers
            
            content = re.sub(attrs_pattern, replace_attrs, content, flags=re.DOTALL)
            
            # 3. Handle states="..." attributes
            states_pattern = r'states\s*=\s*["\']([^"\']*)["\']'
            def replace_states(match):
                nonlocal modifications_made
                states_content = match.group(1)
                try:
                    states_list = [s.strip() for s in states_content.split(',') if s.strip()]
                    if states_list:
                        if len(states_list) == 1:
                            expression = f"state != '{states_list[0]}'"
                        else:
                            states_str = "', '".join(states_list)
                            expression = f"state not in ('{states_str}')"
                        
                        modifications_made = True
                        logger.debug(f"Converted states in {file_path}: {states_content} -> invisible=\"{expression}\"")
                        return f'invisible="{expression}"'
                
                except Exception as e:
                    logger.warning(f"Could not parse states in {file_path}: {states_content}, error: {e}")
                    return f'_states_migration_error="{states_content}"'
                
                return match.group(0)
            
            content = re.sub(states_pattern, replace_states, content)
            
            # 4. Handle invisible -> column_invisible in tree/list views
            def replace_invisible_in_trees(match):
                nonlocal modifications_made
                view_content = match.group(0)
                field_pattern = r'(<field[^>]*?\s)invisible(\s*=\s*["\'][^"\']*["\'])'
                new_content = re.sub(field_pattern, r'\1column_invisible\2', view_content)
                if new_content != view_content:
                    modifications_made = True
                    logger.debug(f"Converted invisible to column_invisible in tree/list view in {file_path}")
                return new_content
            
            tree_list_pattern = r'<(tree|list)[^>]*>.*?</\1>'
            content = re.sub(tree_list_pattern, replace_invisible_in_trees, content, flags=re.DOTALL)
            
            # Only write if actual modifications were made
            if modifications_made and content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                logger.info(f"Updated attrs/states in: {file_path}")
                return True
            else:
                logger.debug(f"No changes needed in: {file_path}")
                return False
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            return False
    
    # Process all XML files
    total_modified = 0
    for xml_file in xml_files:
        if process_single_file(xml_file):
            total_modified += 1
    
    if total_modified > 0:
        logger.info(f"Successfully migrated attrs/states in {total_modified} files from {module_name}")
    else:
        logger.debug(f"No files required attrs/states migration in {module_name}")


def replace_chatter_blocks(logger, module_path, module_name, manifest_path, migration_steps, tools):
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


def replace_deprecated_kanban_box_card_menu(logger, module_path, module_name, manifest_path, migration_steps, tools):
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


def replace_user_has_groups(logger, module_path, module_name, manifest_path, migration_steps, tools):
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


def replace_unaccent_parameter(logger, module_path, module_name, manifest_path, migration_steps, tools):
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
                file, replaces, log_message=f"[18.0] Removed deprecated unaccent parameter in: {file}"
            )
        except Exception as e:
            logger.error(f"Error processing file {file}: {str(e)}")


def replace_ustr(logger, module_path, module_name, manifest_path, migration_steps, tools):
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
            tools._replace_in_file(file, replaces, log_message=f"Deprecate ustr in: {file}")
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
        replace_attrs_and_states,  # Place this last to run after other modifications
    ]