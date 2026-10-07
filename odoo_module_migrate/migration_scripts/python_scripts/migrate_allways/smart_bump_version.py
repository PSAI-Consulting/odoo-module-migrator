import ast
import re

from odoo_module_migrate.manifest import _find_key, _Positions


def bump_revision(**kwargs):
    """
    Intelligently bump version in __manifest__.py file.
    
    This function adapts the version format based on the target version:
    - If current version is simple format like '0.1', it becomes '{target_version}.0.1'  
    - If current version already has target version format like '16.0.1.0.0', 
      it updates to the new target version like '18.0.1.0.0'
    - If current version is in format like '1.0.0', it becomes '{target_version}.1.0.0'
    """
    tools = kwargs["tools"]
    manifest_path = kwargs["manifest_path"]
    migration_steps = kwargs["migration_steps"]
    target_version_name = migration_steps[-1]["target_version_name"]
    
    # Read current manifest content
    manifest_content = tools._read_content(manifest_path)
    
    version_node = _find_key(manifest_content, "version")
    current_version = (
        version_node.value
        if isinstance(version_node, ast.Constant)
        and isinstance(version_node.value, str)
        else None
    )

    if current_version is None:
        # If no version found, set a default one
        new_version = f"{target_version_name}.1.0.0"
        kwargs["logger"].warning("No version found in manifest, setting default version: %s" % new_version)
        try:
            tree = ast.parse(manifest_content)
            mapping = tree.body[0].value
            if not isinstance(mapping, ast.Dict):
                return
            pos = _Positions(manifest_content)
            offset = pos(mapping.lineno, mapping.col_offset) + 1
            indent = " " * 4
            insertion = f'\n{indent}"version": "{new_version}",'
            new_content = manifest_content[:offset] + insertion + manifest_content[offset:]
            tools._write_content(manifest_path, new_content)
            kwargs["logger"].info("Added missing manifest version %s" % new_version)
        except (SyntaxError, ValueError, IndexError, AttributeError):
            return
        return
    else:
        new_version = _adapt_version_format(current_version, target_version_name)

    content = tools._read_content(manifest_path)
    pos = _Positions(content)
    start = pos(version_node.lineno, version_node.col_offset)
    end = pos(version_node.end_lineno, version_node.end_col_offset)
    source = content[start:end]
    quote = source[0] if source[:1] in {"'", '"'} else '"'
    new_content = content[:start] + quote + new_version + quote + content[end:]
    
    if new_content != content:
        tools._write_content(manifest_path, new_content)
        kwargs["logger"].info("Smart bump version to %s" % new_version)


def _adapt_version_format(current_version, target_version_name):
    """
    Adapt version format based on current version pattern.
    
    Examples:
    - '0.1' -> '18.0.0.1' (simple version becomes target.0.simple)  
    - '16.0.1.0.0' -> '18.0.1.0.0' (standard Odoo version format)
    - '16.23.10.27' -> '18.23.10.27' (replace first part with target major)
    - '1.0.0' -> '18.0.1.0.0' (standard version becomes full format)
    """
    version_parts = current_version.split('.')
    target_major = target_version_name.split('.')[0]  # '18' from '18.0'

    # Standard Odoo format 'X.0.a.b.c' (or 'saas~X.Y.a.b.c'): OCA convention,
    # a migrated module restarts at '{target}.1.0.0'
    if re.fullmatch(r"(saas~)?\d+\.\d+\.\d+\.\d+\.\d+", current_version):
        if current_version.startswith(target_version_name + "."):
            return current_version  # already migrated: keep it (idempotence)
        return f"{target_version_name}.1.0.0"

    # The serie alone ('17.0'): '20.0' is refused by Odoo 20.0 ("incompatible
    # version": adapt_version() no longer prefixes a version starting with the
    # serie, and check_version() wants '20.0.' + something)
    if re.fullmatch(r"\d+\.0", current_version) and 8 <= int(version_parts[0]) <= 20:
        return f"{target_version_name}.1.0.0"

    if len(version_parts) >= 2:
        first_part = version_parts[0]
        
        # Check if first part looks like an Odoo major version (8-20)
        if (first_part.isdigit() and 
            int(first_part) >= 8 and int(first_part) <= 20):
            
            # Replace the first part with target major version
            version_parts[0] = target_major
            return '.'.join(version_parts)
    
    # For other formats, create a new version with target prefix
    if len(version_parts) == 1:
        # Single number like '1' -> '18.0.0.1'
        return f"{target_version_name}.0.{current_version}"
    elif len(version_parts) == 2:
        # Two parts like '0.1' -> '18.0.0.1'  
        return f"{target_version_name}.{current_version}"
    else:
        # Multiple parts - respect 5 segment limit
        target_parts = target_version_name.split('.')  # ['18', '0']
        remaining_segments = 5 - len(target_parts)  # 3 segments left
        
        # Take only the first remaining_segments from current version
        additional_parts = version_parts[:remaining_segments]
        return '.'.join(target_parts + additional_parts)
