import re


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
    
    # Find current version using regex
    version_pattern = r"['\"]version['\"][\s]*:[\s]*['\"]([^'\"]+)['\"]"
    version_match = re.search(version_pattern, manifest_content)
    
    if not version_match:
        # If no version found, set a default one
        new_version = f"{target_version_name}.1.0.0"
        kwargs["logger"].warning("No version found in manifest, setting default version: %s" % new_version)
    else:
        current_version = version_match.group(1)
        new_version = _adapt_version_format(current_version, target_version_name)
    
    # Replace version in manifest using a safer approach
    # Read current content and replace manually
    content = tools._read_content(manifest_path)
    
    # Pattern to match version line
    version_pattern = r"(['\"])version(['\"])[\s]*:[\s]*(['\"])([^'\"]+)(['\"])"
    
    def replacement_func(match):
        return match.group(1) + 'version' + match.group(2) + ': ' + match.group(3) + new_version + match.group(5)
    
    new_content = re.sub(version_pattern, replacement_func, content)
    
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