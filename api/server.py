"""
Agent Files Manager — Backend FastAPI
Permet de lister, lire et éditer les fichiers .md et config.yaml des agents Hermes connectés.
"""

import os
import shutil
import json
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Agent Files Manager", version="1.0", root_path="/editor")

# CORS pour le frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Configuration des agents connectés ===
HERMES_BASE = Path("/home/jb/.hermes")
PROFILES_DIR = HERMES_BASE / "profiles"
BACKUP_DIR = Path("/var/backups/hexagroupe-agent-editor")

# Agents connectés (gateways actifs)
CONNECTED_AGENTS = {
    "emmett": {
        "name": "Dr. Emmett Brown",
        "emoji": "🧪",
        "role": "Agent principal / Orchestrateur",
        "base_path": HERMES_BASE,
        "is_default": True,
    },
    "billgates": {
        "name": "Bill Gates",
        "emoji": "💻",
        "role": "CTO technique / Dev full-stack",
        "base_path": PROFILES_DIR / "billgates",
        "is_default": False,
    },
    "didier": {
        "name": "Didier",
        "emoji": "🎯",
        "role": "Agent spécialisé",
        "base_path": PROFILES_DIR / "didier",
        "is_default": False,
    },
}

# Fichiers éditables par agent
EDITABLE_FILES = [
    {"path": "SOUL.md", "label": "SOUL.md", "description": "Personnalité, rôle, règles", "icon": "🧬"},
    {"path": "memories/MEMORY.md", "label": "MEMORY.md", "description": "Mémoire persistante", "icon": "🧠"},
    {"path": "memories/USER.md", "label": "USER.md", "description": "Profil utilisateur", "icon": "👤"},
    {"path": "config.yaml", "label": "config.yaml", "description": "Configuration technique", "icon": "⚙️"},
]


def get_agent_files(agent_id: str) -> list:
    """Liste les fichiers éditables d'un agent avec leur contenu résumé."""
    agent = CONNECTED_AGENTS.get(agent_id)
    if not agent:
        return []

    base = agent["base_path"]
    files = []

    for f in EDITABLE_FILES:
        filepath = base / f["path"]
        exists = filepath.exists()
        size = filepath.stat().st_size if exists else 0
        modified = datetime.fromtimestamp(filepath.stat().st_mtime).isoformat() if exists else None

        files.append({
            "path": f["path"],
            "label": f["label"],
            "description": f["description"],
            "icon": f["icon"],
            "exists": exists,
            "size": size,
            "modified": modified,
        })

    # Ajouter les fichiers mémoire datés (memories/20XX-XX-XX.md)
    memories_dir = base / "memories"
    if memories_dir.exists():
        for mf in sorted(memories_dir.glob("20*.md"), reverse=True):
            rel_path = f"memories/{mf.name}"
            if not any(ef["path"] == rel_path for ef in files):
                files.append({
                    "path": rel_path,
                    "label": mf.name,
                    "description": f"Souvenir du {mf.stem}",
                    "icon": "📅",
                    "exists": True,
                    "size": mf.stat().st_size,
                    "modified": datetime.fromtimestamp(mf.stat().st_mtime).isoformat(),
                })

    return files


# === Routes API ===

@app.get("/api/agents")
def list_agents():
    """Liste les agents connectés avec leurs fichiers."""
    result = []
    for agent_id, agent in CONNECTED_AGENTS.items():
        result.append({
            "id": agent_id,
            "name": agent["name"],
            "emoji": agent["emoji"],
            "role": agent["role"],
            "is_default": agent["is_default"],
            "files": get_agent_files(agent_id),
        })
    return result


@app.get("/api/agents/{agent_id}/files/{file_path:path}")
def read_file(agent_id: str, file_path: str):
    """Lire le contenu d'un fichier agent."""
    agent = CONNECTED_AGENTS.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' non trouvé")

    # Sécurité : empêcher les path traversal
    if ".." in file_path:
        raise HTTPException(400, "Chemin invalide")

    filepath = agent["base_path"] / file_path
    if not filepath.exists():
        raise HTTPException(404, f"Fichier '{file_path}' non trouvé")

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"Erreur lecture : {e}")

    return {
        "agent_id": agent_id,
        "file_path": file_path,
        "content": content,
        "size": len(content),
        "modified": datetime.fromtimestamp(filepath.stat().st_mtime).isoformat(),
    }


class SaveRequest(BaseModel):
    content: str


@app.put("/api/agents/{agent_id}/files/{file_path:path}")
def save_file(agent_id: str, file_path: str, req: SaveRequest):
    """Sauvegarder un fichier agent (avec backup automatique)."""
    agent = CONNECTED_AGENTS.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' non trouvé")

    # Sécurité : empêcher les path traversal
    if ".." in file_path:
        raise HTTPException(400, "Chemin invalide")

    # Vérifier que c'est un fichier autorisé
    allowed_extensions = {".md", ".yaml", ".yml"}
    ext = Path(file_path).suffix.lower()
    if ext not in allowed_extensions:
        raise HTTPException(400, f"Extension '{ext}' non autorisée")

    filepath = agent["base_path"] / file_path

    # Backup avant modification
    if filepath.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{agent_id}__{file_path.replace('/', '__')}__{timestamp}.bak"
        backup_path = BACKUP_DIR / backup_name
        try:
            shutil.copy2(filepath, backup_path)
        except Exception as e:
            raise HTTPException(500, f"Erreur backup : {e}")

    # Écriture du fichier
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(req.content, encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"Erreur écriture : {e}")

    return {
        "status": "ok",
        "agent_id": agent_id,
        "file_path": file_path,
        "size": len(req.content),
        "modified": datetime.fromtimestamp(filepath.stat().st_mtime).isoformat(),
        "message": f"✅ Fichier sauvegardé (backup créé)",
    }


@app.get("/api/search")
def search_files(q: str):
    """Rechercher un texte dans tous les fichiers des agents connectés."""
    if len(q) < 2:
        raise HTTPException(400, "Requête trop courte (min 2 caractères)")

    results = []
    for agent_id, agent in CONNECTED_AGENTS.items():
        for f in EDITABLE_FILES:
            filepath = agent["base_path"] / f["path"]
            if filepath.exists():
                try:
                    content = filepath.read_text(encoding="utf-8")
                    if q.lower() in content.lower():
                        # Trouver les lignes correspondantes
                        lines = content.split("\n")
                        matches = []
                        for i, line in enumerate(lines):
                            if q.lower() in line.lower():
                                matches.append({"line": i + 1, "text": line.strip()[:200]})
                        results.append({
                            "agent_id": agent_id,
                            "agent_name": agent["name"],
                            "file_path": f["path"],
                            "file_label": f["label"],
                            "matches": matches[:10],
                        })
                except Exception:
                    pass
    return results


# Servir le frontend
STATIC_DIR = Path(__file__).parent.parent / "static"

@app.get("/")
def serve_index():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "Agent Files Manager API", "docs": "/docs"}

@app.get("/{path:path}")
def serve_static(path: str):
    """Servir les fichiers statiques du frontend."""
    file = STATIC_DIR / path
    if file.exists() and file.is_file():
        return FileResponse(file)
    # Fallback vers index.html pour SPA
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9475)
