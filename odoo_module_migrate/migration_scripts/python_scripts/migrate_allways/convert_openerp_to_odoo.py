import re


def convert_xml_tags(**kwargs):
    """
    Convert <openerp> tags to <odoo> tags in XML files automatically.
    This is a common migration task needed for most Odoo upgrades.
    """
    tools = kwargs["tools"]
    module_path = kwargs["module_path"]
    logger = kwargs["logger"]
    
    # Get all XML files in the module
    xml_files = tools.get_files(module_path, [".xml"])
    
    converted_files = 0
    
    for xml_file in xml_files:
        try:
            # Read file content
            content = tools._read_content(xml_file)
            
            # Check if file contains <openerp> tags
            if "<openerp>" in content or "</openerp>" in content:
                # Replace <openerp> with <odoo>
                new_content = content.replace("<openerp>", "<odoo>")
                new_content = new_content.replace("</openerp>", "</odoo>")
                
                # Write back if changed
                if new_content != content:
                    tools._write_content(xml_file, new_content)
                    converted_files += 1
                    logger.info(f"Converted <openerp> to <odoo> tags in file: {xml_file.name}")
                    
        except Exception as e:
            logger.warning(f"Failed to process XML file {xml_file}: {e}")
    
    if converted_files > 0:
        logger.info(f"Converted {converted_files} XML files from <openerp> to <odoo> tags")
    else:
        logger.debug("No XML files with <openerp> tags found")