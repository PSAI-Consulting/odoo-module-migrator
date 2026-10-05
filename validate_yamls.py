import os
import glob
import yaml
import sys
from typing import Dict, List, Any

# Map folder names to expected structure types based on BaseMigrationScript
TYPE_ARRAY = "TYPE_ARRAY"
TYPE_DICT = "TYPE_DICT"
TYPE_DICT_OF_DICT = "TYPE_DICT_OF_DICT"

RULE_TYPES = {
    "text_replaces": TYPE_DICT_OF_DICT,
    "text_errors": TYPE_DICT_OF_DICT,
    "text_warnings": TYPE_DICT_OF_DICT,
    "deprecated_modules": TYPE_ARRAY,
    "file_renames": TYPE_DICT,
    "removed_fields": TYPE_ARRAY,
    "renamed_fields": TYPE_ARRAY,
    "renamed_models": TYPE_ARRAY,
    "removed_models": TYPE_ARRAY,
}

def validate_yaml_file(filepath: str, rule_type: str) -> List[str]:
    errors = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            
        if data is None:
             return []

        if rule_type == TYPE_ARRAY:
            if not isinstance(data, list):
                errors.append(f"Expected a list (ARRAY), got {type(data).__name__}")
        elif rule_type == TYPE_DICT:
            if not isinstance(data, dict):
                errors.append(f"Expected a dictionary (DICT), got {type(data).__name__}")
        elif rule_type == TYPE_DICT_OF_DICT:
            if not isinstance(data, dict):
                errors.append(f"Expected a dictionary of dictionaries (DICT_OF_DICT), got {type(data).__name__}")
            else:
                for key, value in data.items():
                    if not isinstance(value, dict):
                        errors.append(f"Key '{key}' expected to contain a dictionary, got {type(value).__name__}")
        
    except yaml.YAMLError as exc:
        errors.append(f"YAML Syntax Error: {exc}")
    except Exception as e:
        errors.append(f"General Error: {e}")
        
    return errors

def main():
    base_dir = r"c:\Odoo\local-addons\odoo-module-migrator\odoo_module_migrate\migration_scripts"
    
    total_files = 0
    valid_files = 0
    invalid_files = 0
    
    with open("validation_report.txt", "w", encoding='utf-8') as report:
        report.write(f"Scanning for YAML files in {base_dir}...\n")
        
        for folder_name, rule_type in RULE_TYPES.items():
            search_path = os.path.join(base_dir, folder_name, "**", "*.yaml")
            files = glob.glob(search_path, recursive=True)
            
            for file_path in files:
                total_files += 1
                file_errors = validate_yaml_file(file_path, rule_type)
                
                rel_path = os.path.relpath(file_path, base_dir)
                if file_errors:
                    invalid_files += 1
                    report.write(f"[FAIL] {rel_path}\n")
                    for err in file_errors:
                        report.write(f"  - {err}\n")
                else:
                    valid_files += 1

        report.write("-" * 40 + "\n")
        report.write(f"Total YAML files checked: {total_files}\n")
        report.write(f"Valid: {valid_files}\n")
        report.write(f"Invalid: {invalid_files}\n")

if __name__ == "__main__":
    main()
