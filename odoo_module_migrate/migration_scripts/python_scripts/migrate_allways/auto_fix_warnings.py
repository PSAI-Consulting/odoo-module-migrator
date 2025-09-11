# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""
Automatic field rename and removed imports fixes
Replaces renamed fields and removes deprecated imports
"""

import os
import re
import yaml
import glob


def _get_renamed_fields_rules(migration_scripts_dir, from_version, to_version):
    """Get all renamed fields rules from YAML files for all migration steps"""
    rules = []
    
    if from_version == "16.0" and to_version == "18.0":
        migration_steps = ["migrate_160_170", "migrate_170_180"]
    elif from_version == "16.0" and to_version == "17.0":
        migration_steps = ["migrate_160_170"]
    else:
        migrate_pattern = f"migrate_{from_version.replace('.', '')}_{to_version.replace('.', '')}"
        migration_steps = [migrate_pattern]
    
    for migrate_pattern in migration_steps:
        pattern = os.path.join(migration_scripts_dir, "renamed_fields", migrate_pattern, "*.yaml")
        yaml_files = glob.glob(pattern)
        
        for yaml_file in yaml_files:
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    yaml_rules = yaml.safe_load(f) or []
                    rules.extend(yaml_rules)
            except Exception:
                pass
    
    return rules


def _get_removed_imports_rules(migration_scripts_dir, from_version, to_version):
    """Get all removed imports rules from YAML files for all migration steps"""
    rules = []
    
    if from_version == "16.0" and to_version == "18.0":
        migration_steps = ["migrate_160_170", "migrate_170_180"]
    elif from_version == "16.0" and to_version == "17.0":
        migration_steps = ["migrate_160_170"]
    else:
        migrate_pattern = f"migrate_{from_version.replace('.', '')}_{to_version.replace('.', '')}"
        migration_steps = [migrate_pattern]
    
    for migrate_pattern in migration_steps:
        pattern = os.path.join(migration_scripts_dir, "removed_imports", migrate_pattern, "*.yaml")
        yaml_files = glob.glob(pattern)
        
        for yaml_file in yaml_files:
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    yaml_rules = yaml.safe_load(f) or []
                    rules.extend(yaml_rules)
            except Exception:
                pass
    
    return rules


def _fix_python_field_renames(file_path, renamed_fields):
    """Fix renamed fields in Python files"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        for model_name, old_field, new_field, commit_info in renamed_fields:
            # String literals 'old_field' -> 'new_field'
            pattern1 = rf"(['\"]){re.escape(old_field)}\1"
            replacement1 = rf"\1{new_field}\1"
            content = re.sub(pattern1, replacement1, content)
            
            # Dot notation .old_field -> .new_field
            pattern2 = rf"\.{re.escape(old_field)}\b"
            replacement2 = f".{new_field}"
            content = re.sub(pattern2, replacement2, content)
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
            
        return False
        
    except Exception:
        return False


def _fix_removed_imports(file_path, removed_imports):
    """Remove deprecated imports from Python files"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        for import_rule in removed_imports:
            old_import = import_rule.get('old_import', '')
            replacement = import_rule.get('replacement', '')
            
            if not old_import:
                continue
            
            # Case 1: Full import line removal (like "import warnings")
            if old_import.startswith('import ') or old_import.startswith('from '):
                if replacement:
                    content = content.replace(old_import, replacement)
                else:
                    # Remove the entire line
                    lines = content.split('\n')
                    new_lines = [line for line in lines if old_import not in line]
                    content = '\n'.join(new_lines)
            
            # Case 2: Remove specific import from import list (like "Warning" from "from odoo.exceptions import Warning, UserError")
            else:
                # Pattern for removing specific import from list
                # Handle "Warning ," or "Warning," (with comma after, any spaces)
                pattern1 = rf'\b{re.escape(old_import)}\s*,\s*'
                content = re.sub(pattern1, '', content)
                
                # Handle " ,Warning" or ", Warning" or ",Warning" (with comma before, any spaces)  
                pattern2 = rf'\s*,\s*\b{re.escape(old_import)}\b'
                content = re.sub(pattern2, '', content)
                
                # Handle single import "Warning" (only one in the list)
                pattern3 = rf'import\s+{re.escape(old_import)}\b'
                if replacement:
                    content = re.sub(pattern3, f'import {replacement}', content)
                else:
                    # Remove the entire import line if it's the only import
                    lines = content.split('\n')
                    new_lines = []
                    for line in lines:
                        if re.search(pattern3, line) and ',' not in line:
                            continue  # Skip this line
                        else:
                            new_lines.append(line)
                    content = '\n'.join(new_lines)
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
            
        return False
        
    except Exception:
        return False


def _fix_xml_field_renames(file_path, renamed_fields):
    """Fix renamed fields in XML files"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        for model_name, old_field, new_field, commit_info in renamed_fields:
            # Pattern: name="old_field" -> name="new_field"
            pattern1 = rf'(name\s*=\s*["\']){re.escape(old_field)}(["\'])'
            replacement1 = rf'\1{new_field}\2'
            content = re.sub(pattern1, replacement1, content)
            
            # Pattern: ref="model.old_field" -> ref="model.new_field"
            pattern2 = rf'(ref\s*=\s*["\'][^"\']*\.){re.escape(old_field)}(["\'])'
            replacement2 = rf'\1{new_field}\2'
            content = re.sub(pattern2, replacement2, content)
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
            
        return False
        
    except Exception:
        return False


def auto_fix_migration_warnings(**kwargs):
    """Main function to automatically fix migration warnings"""
    logger = kwargs.get('logger')
    module_path = kwargs.get('module_path')
    migration_steps = kwargs.get('migration_steps')
    
    if not logger or not module_path:
        return
    
    # Determine target version
    target_version = "18.0"
    if migration_steps:
        for step in migration_steps:
            if "170_180" in step:
                target_version = "18.0"
                break
            elif "160_170" in step and "170_180" not in str(migration_steps):
                target_version = "17.0"
    
    # Get migration scripts directory
    current_file = __file__
    migration_scripts_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
    
    # Get rules
    from_version = "16.0"
    renamed_fields = _get_renamed_fields_rules(migration_scripts_dir, from_version, target_version)
    removed_imports = _get_removed_imports_rules(migration_scripts_dir, from_version, target_version)
    
    files_modified = 0
    
    # Process all Python and XML files
    for root, dirs, files in os.walk(module_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__']]
        
        for file in files:
            file_path = os.path.join(root, file)
            
            if file.endswith('.py'):
                if _fix_python_field_renames(file_path, renamed_fields):
                    files_modified += 1
                if _fix_removed_imports(file_path, removed_imports):
                    files_modified += 1
                    
            elif file.endswith('.xml'):
                if _fix_xml_field_renames(file_path, renamed_fields):
                    files_modified += 1
    
    if files_modified > 0:
        logger.info(f"Auto-fix completed: {files_modified} files modified")