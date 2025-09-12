# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

"""OCA modules list generator."""

import os
import pathlib
from datetime import datetime

from .config import _MANIFEST_NAMES
from .log import logger


def generate_oca_file_list(directory_path):
    """
    Generate OCA_MODULES.md file by scanning all modules in the directory.
    """
    project_path = pathlib.Path(directory_path).resolve()
    md_file = project_path / "OCA_MODULES.md"
    
    def is_oca_module(module_path):
        """Check if a module is OCA using existing logic from migration.py"""
        for manifest_name in _MANIFEST_NAMES:
            manifest_path = module_path / manifest_name
            if manifest_path.exists():
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    manifest_data = eval(content)
                    if isinstance(manifest_data, dict):
                        author = manifest_data.get('author', '')
                        if 'Odoo Community Association (OCA)' in author:
                            return True, manifest_data
                    if 'Odoo Community Association (OCA)' in content:
                        return True, {}
                except Exception:
                    pass
        return False, {}
    
    def extract_github_repo(website_url):
        """Extract OCA repository name from GitHub URL."""
        if not website_url or 'github.com' not in website_url:
            return "OCA/unknown"
        try:
            if '/OCA/' in website_url:
                parts = website_url.split('/OCA/')
                if len(parts) > 1:
                    repo_name = parts[1].rstrip('/').split('/')[0]  # Take only repo name
                    return f"OCA/{repo_name}"
        except Exception:
            pass
        return "OCA/unknown"
    
    # Find all OCA modules in the project
    oca_modules = []
    child_paths = [x for x in project_path.iterdir() if x.is_dir()]
    
    for child_path in child_paths:
        # Check if it's a valid module (has manifest)
        if any([(child_path / x).exists() for x in _MANIFEST_NAMES]):
            is_oca, manifest_data = is_oca_module(child_path)
            if is_oca:
                website = manifest_data.get('website', '')
                repo = extract_github_repo(website)
                summary = manifest_data.get('summary', '')
                version = manifest_data.get('version', '')
                
                oca_modules.append({
                    'name': child_path.name,
                    'repo': repo,
                    'website': website,
                    'summary': summary,
                    'version': version,
                })
                logger.debug(f"Found OCA module: {child_path.name} -> {repo}")
    
    # Generate complete markdown file
    if oca_modules:
        md_content = f"""# Modules OCA présents dans le projet

Cette liste répertorie tous les modules de l'Odoo Community Association (OCA) trouvés dans le projet. 
Ces modules sont maintenus par la communauté et doivent être mis à jour via leurs dépôts Git officiels.

*⚠️ Cette liste est générée automatiquement - ne pas modifier manuellement*

## 📋 Liste des modules OCA

"""
        
        # Add all OCA modules
        for module in sorted(oca_modules, key=lambda x: x['name']):
            name = module['name']
            repo = module['repo']
            github_url = f"https://github.com/{repo}"
            summary = module.get('summary', '')
            version = module.get('version', '')
            
            module_line = f"- [ ] **{name}** - [{repo}]({github_url})"
            if summary:
                module_line += f" - *{summary}*"
            if version:
                module_line += f" (v{version})"
            md_content += module_line + "\n"
        
        # Add footer
        unique_repos = set(module['repo'] for module in oca_modules)
        
        md_content += f"""
## 📊 Statistiques

- **Total de modules OCA** : {len(oca_modules)}
- **Dépôts GitHub impliqués** : {len(unique_repos)}

## 🔄 Processus de mise à jour

1. ✅ Cocher les modules à mettre à jour dans cette liste
2. 🔗 Cliquer sur le lien GitHub correspondant  
3. 🔍 Vérifier la compatibilité avec la version d'Odoo ciblée (branches/tags)
4. 📥 Télécharger/cloner la version appropriée
5. 🧪 Tester en environnement de développement
6. 🚀 Déployer en production après validation

## ⚠️ Important

- Ces modules ne doivent **JAMAIS** être modifiés par l'équipe de développement interne
- Toute personnalisation doit être faite dans des modules séparés qui héritent des modules OCA
- Utiliser `--no-oca-modules` lors des migrations pour les ignorer automatiquement
- Les URLs GitHub sont extraites automatiquement des manifests des modules

---
*Liste générée automatiquement le {datetime.now().strftime('%d/%m/%Y à %H:%M')} avec odoo-module-migrator*
"""
        
        # Write complete file
        try:
            with open(md_file, 'w', encoding='utf-8') as f:
                f.write(md_content)
            print(f"[OK] Generated OCA_MODULES.md with {len(oca_modules)} modules: {md_file}")
            logger.info(f"Generated complete OCA_MODULES.md with {len(oca_modules)} modules: {md_file}")
        except Exception as e:
            print(f"[ERROR] Failed to generate OCA modules file: {e}")
            logger.error(f"Failed to generate OCA modules file: {e}")
    else:
        print("[INFO] No OCA modules found in project")
        logger.info("No OCA modules found in project")