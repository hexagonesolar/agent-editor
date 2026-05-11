"""
Agent Files Manager — Backend FastAPI v2.0
Features: auth, versioning, analyze, improve wizard
"""

import os
import re
import shutil
import json
import secrets
import hashlib
import difflib
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Agent Files Manager", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# === AUTH ===
AUTH_CONFIG = Path(__file__).parent / "auth.json"

def load_auth_config():
    if AUTH_CONFIG.exists():
        return json.loads(AUTH_CONFIG.read_text())
    default = {
        "users": {
            "jb": {"password_hash": hashlib.sha256("hexagone2026".encode()).hexdigest(), "role": "admin"}
        },
        "session_secret": secrets.token_hex(32),
    }
    AUTH_CONFIG.write_text(json.dumps(default, indent=2))
    return default

AUTH = load_auth_config()
active_sessions: dict[str, dict] = {}

def verify_password(username: str, password: str) -> bool:
    user = AUTH.get("users", {}).get(username)
    if not user:
        return False
    return user["password_hash"] == hashlib.sha256(password.encode()).hexdigest()

def get_current_user(request: Request) -> dict:
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in active_sessions:
        raise HTTPException(401, "Non authentifié")
    return active_sessions[session_id]

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/login")
def login(req: LoginRequest, response: Response):
    if not verify_password(req.username, req.password):
        raise HTTPException(401, "Identifiants incorrects")
    session_id = secrets.token_hex(32)
    active_sessions[session_id] = {
        "username": req.username,
        "role": AUTH["users"][req.username]["role"],
        "login_time": datetime.now().isoformat(),
    }
    response = JSONResponse({"status": "ok", "username": req.username})
    response.set_cookie(key="session_id", value=session_id, httponly=True, secure=True, samesite="lax", max_age=86400 * 7)
    return response

@app.post("/api/logout")
def logout(request: Request, response: Response):
    session_id = request.cookies.get("session_id")
    if session_id and session_id in active_sessions:
        del active_sessions[session_id]
    response = JSONResponse({"status": "ok"})
    response.delete_cookie("session_id")
    return response

@app.get("/api/me")
def get_me(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in active_sessions:
        raise HTTPException(401, "Non authentifié")
    return active_sessions[session_id]


# === CONFIG ===
HERMES_BASE = Path("/home/jb/.hermes")
PROFILES_DIR = HERMES_BASE / "profiles"
BACKUP_DIR = Path("/var/backups/hexagroupe-agent-editor")
VERSIONS_DIR = BACKUP_DIR / "versions"
MAX_VERSIONS = 20

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

EDITABLE_FILES = [
    {"path": "SOUL.md", "label": "SOUL.md", "description": "Personnalité, rôle, règles", "icon": "🧬"},
    {"path": "memories/MEMORY.md", "label": "MEMORY.md", "description": "Mémoire persistante", "icon": "🧠"},
    {"path": "memories/USER.md", "label": "USER.md", "description": "Profil utilisateur", "icon": "👤"},
    {"path": "config.yaml", "label": "config.yaml", "description": "Configuration technique", "icon": "⚙️"},
]


def get_agent_files(agent_id: str) -> list:
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
        # Compter les versions
        version_count = count_versions(agent_id, f["path"])
        files.append({
            "path": f["path"],
            "label": f["label"],
            "description": f["description"],
            "icon": f["icon"],
            "exists": exists,
            "size": size,
            "modified": modified,
            "versions": version_count,
        })
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
                    "versions": count_versions(agent_id, rel_path),
                })
    return files


# === VERSIONING ===
def get_version_dir(agent_id: str, file_path: str) -> Path:
    safe_name = file_path.replace("/", "__").replace(".", "_")
    vdir = VERSIONS_DIR / agent_id / safe_name
    vdir.mkdir(parents=True, exist_ok=True)
    return vdir

def save_version(agent_id: str, file_path: str, content: str):
    """Sauvegarder une version du fichier."""
    vdir = get_version_dir(agent_id, file_path)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    version_file = vdir / f"{ts}.txt"
    version_file.write_text(content, encoding="utf-8")
    # Rotation : garder les MAX_VERSIONS dernières
    versions = sorted(vdir.glob("*.txt"), reverse=True)
    for old in versions[MAX_VERSIONS:]:
        old.unlink()

def count_versions(agent_id: str, file_path: str) -> int:
    vdir = get_version_dir(agent_id, file_path)
    return len(list(vdir.glob("*.txt")))

def list_versions(agent_id: str, file_path: str) -> list:
    vdir = get_version_dir(agent_id, file_path)
    versions = []
    for vf in sorted(vdir.glob("*.txt"), reverse=True):
        ts_str = vf.stem  # 20260511_094500
        try:
            dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
        except ValueError:
            dt = datetime.fromtimestamp(vf.stat().st_mtime)
        versions.append({
            "timestamp": ts_str,
            "date": dt.strftime("%d/%m/%Y"),
            "time": dt.strftime("%H:%M:%S"),
            "iso": dt.isoformat(),
            "size": vf.stat().st_size,
        })
    return versions


# === ANALYZE ===
def analyze_file(file_path: str, content: str) -> dict:
    """Analyse automatique d'un fichier — détecte les problèmes et opportunités."""
    filename = file_path.split("/")[-1]
    issues = []
    score = 100
    char_count = len(content)
    line_count = len(content.split("\n"))
    word_count = len(content.split())
    headers = re.findall(r'^#{1,3}\s+.+', content, re.MULTILINE)

    if filename == "SOUL.md":
        # Taille
        if char_count > 5000:
            issues.append({"severity": "warning", "icon": "📏", "title": "Fichier trop long", "desc": f"{char_count} caractères. Au-delà de 5000, les instructions centrales se diluent. L'agent retient mieux les infos en début et fin.", "category": "structure"})
            score -= 15
        elif char_count < 200:
            issues.append({"severity": "danger", "icon": "📭", "title": "Fichier trop court", "desc": f"Seulement {char_count} caractères. L'agent n'a pas assez de contexte pour bien se comporter.", "category": "structure"})
            score -= 25
        # Structure
        if len(headers) < 2:
            issues.append({"severity": "warning", "icon": "📐", "title": "Pas de structure", "desc": "Utilise des ## sections (Identité, Rôle, Règles, Style) pour que l'agent parse mieux les instructions.", "category": "structure"})
            score -= 10
        # Règles négatives
        neg_patterns = re.findall(r'(?:jamais|ne pas|interdit|ne .*? pas|never|don\'t|forbidden)', content, re.IGNORECASE)
        if len(neg_patterns) == 0:
            issues.append({"severity": "info", "icon": "🚫", "title": "Pas de contraintes négatives", "desc": "Dire à l'agent ce qu'il ne doit PAS faire est souvent plus efficace que de dire ce qu'il doit faire.", "category": "content"})
            score -= 5
        # Ton / style
        style_patterns = re.findall(r'(?:ton|style|voix|langage|langue|français|formel|décontracté|technique)', content, re.IGNORECASE)
        if len(style_patterns) == 0:
            issues.append({"severity": "info", "icon": "🗣️", "title": "Ton non défini", "desc": "Définis le style de communication (formel, décontracté, technique, etc.) pour des réponses cohérentes.", "category": "content"})
            score -= 5
        # Vague
        vague = re.findall(r'(?:sois? utile|sois? gentil|be helpful|be nice|be friendly)', content, re.IGNORECASE)
        if vague:
            issues.append({"severity": "warning", "icon": "🌫️", "title": "Instructions trop vagues", "desc": f"Expressions vagues détectées : {', '.join(vague[:3])}. Remplace par des comportements précis.", "category": "content"})
            score -= 10
        # Exemples
        example_patterns = re.findall(r'(?:exemple|example|ex\s?:|par exemple)', content, re.IGNORECASE)
        if len(example_patterns) == 0 and char_count > 500:
            issues.append({"severity": "info", "icon": "💡", "title": "Pas d'exemples", "desc": "Ajouter 1-2 exemples de réponses idéales calibre le style de l'agent bien mieux que des règles abstraites.", "category": "content"})
            score -= 5

    elif filename == "MEMORY.md":
        if char_count > 4000:
            issues.append({"severity": "warning", "icon": "📏", "title": "Mémoire trop volumineuse", "desc": f"{char_count} caractères. La mémoire est injectée à CHAQUE tour — au-delà de 4000 chars, ça consomme des tokens inutilement.", "category": "size"})
            score -= 15
        if char_count < 50:
            issues.append({"severity": "info", "icon": "📭", "title": "Mémoire quasi vide", "desc": "L'agent n'a presque rien en mémoire. Il repart de zéro à chaque conversation.", "category": "content"})
            score -= 5
        # Structure
        bullet_lines = len(re.findall(r'^[\s]*[-*•]\s', content, re.MULTILINE))
        total_non_empty = len([l for l in content.split("\n") if l.strip()])
        if total_non_empty > 5 and bullet_lines / max(total_non_empty, 1) < 0.3:
            issues.append({"severity": "warning", "icon": "📋", "title": "Format prose détecté", "desc": "La mémoire fonctionne mieux en listes à puces (bullet points) qu'en paragraphes. Plus facile à parser pour l'agent.", "category": "structure"})
            score -= 10
        # Instructions vs faits
        imperative = re.findall(r'^(?:toujours|always|run|execute|faire|lancer|utiliser|use)\s', content, re.IGNORECASE | re.MULTILINE)
        if len(imperative) > 2:
            issues.append({"severity": "warning", "icon": "⚠️", "title": "Instructions au lieu de faits", "desc": f"{len(imperative)} lignes impératives détectées. La mémoire doit stocker des faits ('Projet X utilise Python'), pas des ordres ('Utiliser Python').", "category": "content"})
            score -= 10
        # Doublons potentiels
        lines = [l.strip().lower() for l in content.split("\n") if len(l.strip()) > 20]
        seen = set()
        dupes = 0
        for l in lines:
            simple = re.sub(r'[^\w\s]', '', l)
            if simple in seen:
                dupes += 1
            seen.add(simple)
        if dupes > 0:
            issues.append({"severity": "warning", "icon": "♻️", "title": f"{dupes} doublon(s) potentiel(s)", "desc": "Des lignes quasi-identiques ont été détectées. Déduplique pour garder la mémoire compacte.", "category": "content"})
            score -= 5 * min(dupes, 3)

    elif filename == "USER.md":
        if char_count < 100:
            issues.append({"severity": "danger", "icon": "📭", "title": "Profil trop vide", "desc": "L'agent ne sait presque rien sur toi. Ajoute au moins : nom, timezone, niveau technique, préférences de communication.", "category": "content"})
            score -= 25
        expertise_patterns = re.findall(r'(?:technique|dev|développeur|non.?dev|expert|débutant|level|niveau)', content, re.IGNORECASE)
        if not expertise_patterns:
            issues.append({"severity": "warning", "icon": "🔧", "title": "Niveau technique non défini", "desc": "L'agent ne sait pas si tu es dev ou non. Il ne peut pas calibrer ses explications.", "category": "content"})
            score -= 10
        comm_patterns = re.findall(r'(?:concis|détaillé|bref|formel|décontracté|ton|style|préfère)', content, re.IGNORECASE)
        if not comm_patterns:
            issues.append({"severity": "info", "icon": "💬", "title": "Préférences de communication absentes", "desc": "Dis à l'agent comment tu aimes les réponses : courtes ou détaillées, formelles ou décontractées.", "category": "content"})
            score -= 5
        tz_patterns = re.findall(r'(?:timezone|fuseau|UTC|GMT|CET|heure)', content, re.IGNORECASE)
        if not tz_patterns:
            issues.append({"severity": "info", "icon": "🕐", "title": "Pas de timezone", "desc": "Utile pour les rappels, crons, et toute référence temporelle.", "category": "content"})
            score -= 3

    elif filename == "config.yaml":
        if "model:" not in content:
            issues.append({"severity": "danger", "icon": "🤖", "title": "Pas de modèle défini", "desc": "Le config.yaml n'a pas de section model:. L'agent utilise le modèle par défaut.", "category": "config"})
            score -= 20
        # Indentation check
        tabs = re.findall(r'\t', content)
        if tabs:
            issues.append({"severity": "danger", "icon": "⚠️", "title": "Tabulations détectées", "desc": "YAML n'accepte que les espaces, pas les tabulations. Cela peut casser le chargement.", "category": "syntax"})
            score -= 20

    return {
        "score": max(0, min(100, score)),
        "issues": issues,
        "stats": {
            "characters": char_count,
            "lines": line_count,
            "words": word_count,
            "headers": len(headers),
        }
    }


# === ROUTES API ===

@app.get("/api/agents")
def api_list_agents(user: dict = Depends(get_current_user)):
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
def api_read_file(agent_id: str, file_path: str, user: dict = Depends(get_current_user)):
    agent = CONNECTED_AGENTS.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' non trouvé")
    if ".." in file_path:
        raise HTTPException(400, "Chemin invalide")
    filepath = agent["base_path"] / file_path
    if not filepath.exists():
        raise HTTPException(404, f"Fichier '{file_path}' non trouvé")
    content = filepath.read_text(encoding="utf-8")
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
def api_save_file(agent_id: str, file_path: str, req: SaveRequest, user: dict = Depends(get_current_user)):
    agent = CONNECTED_AGENTS.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' non trouvé")
    if ".." in file_path:
        raise HTTPException(400, "Chemin invalide")
    allowed = {".md", ".yaml", ".yml"}
    if Path(file_path).suffix.lower() not in allowed:
        raise HTTPException(400, "Extension non autorisée")
    filepath = agent["base_path"] / file_path
    # Sauvegarder la version actuelle avant modification
    if filepath.exists():
        old_content = filepath.read_text(encoding="utf-8")
        save_version(agent_id, file_path, old_content)
    # Écriture
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(req.content, encoding="utf-8")
    return {
        "status": "ok",
        "agent_id": agent_id,
        "file_path": file_path,
        "size": len(req.content),
        "modified": datetime.fromtimestamp(filepath.stat().st_mtime).isoformat(),
        "message": "✅ Fichier sauvegardé (version créée)",
    }


# === VERSIONING ROUTES (avant les routes file catch-all) ===

@app.get("/api/agents/{agent_id}/versions/{file_path:path}")
def api_list_versions(agent_id: str, file_path: str, user: dict = Depends(get_current_user)):
    if agent_id not in CONNECTED_AGENTS:
        raise HTTPException(404)
    return list_versions(agent_id, file_path)

@app.get("/api/agents/{agent_id}/version-content/{file_path:path}/{timestamp}")
def api_read_version(agent_id: str, file_path: str, timestamp: str, user: dict = Depends(get_current_user)):
    if agent_id not in CONNECTED_AGENTS:
        raise HTTPException(404)
    vdir = get_version_dir(agent_id, file_path)
    vfile = vdir / f"{timestamp}.txt"
    if not vfile.exists():
        raise HTTPException(404, "Version non trouvée")
    return {"timestamp": timestamp, "content": vfile.read_text(encoding="utf-8")}

@app.post("/api/agents/{agent_id}/restore/{file_path:path}/{timestamp}")
def api_restore_version(agent_id: str, file_path: str, timestamp: str, user: dict = Depends(get_current_user)):
    agent = CONNECTED_AGENTS.get(agent_id)
    if not agent:
        raise HTTPException(404)
    vdir = get_version_dir(agent_id, file_path)
    vfile = vdir / f"{timestamp}.txt"
    if not vfile.exists():
        raise HTTPException(404, "Version non trouvée")
    filepath = agent["base_path"] / file_path
    if filepath.exists():
        save_version(agent_id, file_path, filepath.read_text(encoding="utf-8"))
    old_content = vfile.read_text(encoding="utf-8")
    filepath.write_text(old_content, encoding="utf-8")
    return {"status": "ok", "message": "✅ Version restaurée"}

@app.get("/api/agents/{agent_id}/diff/{file_path:path}/{timestamp}")
def api_diff_version(agent_id: str, file_path: str, timestamp: str, user: dict = Depends(get_current_user)):
    agent = CONNECTED_AGENTS.get(agent_id)
    if not agent:
        raise HTTPException(404)
    vdir = get_version_dir(agent_id, file_path)
    vfile = vdir / f"{timestamp}.txt"
    if not vfile.exists():
        raise HTTPException(404)
    filepath = agent["base_path"] / file_path
    current = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
    old = vfile.read_text(encoding="utf-8")
    diff = list(difflib.unified_diff(old.splitlines(keepends=True), current.splitlines(keepends=True), fromfile=f"v{timestamp}", tofile="actuel", lineterm=""))
    return {"diff": diff, "old_size": len(old), "new_size": len(current)}


# === ANALYZE ROUTE ===

@app.get("/api/agents/{agent_id}/analyze/{file_path:path}")
def api_analyze(agent_id: str, file_path: str, user: dict = Depends(get_current_user)):
    agent = CONNECTED_AGENTS.get(agent_id)
    if not agent:
        raise HTTPException(404)
    filepath = agent["base_path"] / file_path
    if not filepath.exists():
        raise HTTPException(404)
    content = filepath.read_text(encoding="utf-8")
    return analyze_file(file_path, content)


# === IMPROVE ===
from api.improve_engine import generate_proposals, apply_proposals

@app.get("/api/agents/{agent_id}/improve/{file_path:path}")
def api_improve(agent_id: str, file_path: str, user: dict = Depends(get_current_user)):
    """Génère les propositions d'amélioration pour un fichier."""
    agent = CONNECTED_AGENTS.get(agent_id)
    if not agent:
        raise HTTPException(404)
    filepath = agent["base_path"] / file_path
    if not filepath.exists():
        raise HTTPException(404)
    content = filepath.read_text(encoding="utf-8")
    proposals = generate_proposals(file_path, content)
    return {"proposals": proposals, "original": content}


class ImproveDecision(BaseModel):
    id: str
    accepted: bool
    custom_text: Optional[str] = None

class ApplyImproveRequest(BaseModel):
    decisions: list[ImproveDecision]

@app.post("/api/agents/{agent_id}/apply-improve/{file_path:path}")
def api_apply_improve(agent_id: str, file_path: str, req: ApplyImproveRequest, user: dict = Depends(get_current_user)):
    """Applique les propositions acceptées au fichier."""
    agent = CONNECTED_AGENTS.get(agent_id)
    if not agent:
        raise HTTPException(404)
    filepath = agent["base_path"] / file_path
    if not filepath.exists():
        raise HTTPException(404)
    
    original = filepath.read_text(encoding="utf-8")
    
    # Regénérer les propositions pour avoir les métadonnées
    proposals = generate_proposals(file_path, original)
    
    # Appliquer
    decisions = [d.model_dump() for d in req.decisions]
    new_content = apply_proposals(original, proposals, decisions)
    
    # Backup via versioning
    save_version(agent_id, file_path, original)
    
    # Écriture
    filepath.write_text(new_content, encoding="utf-8")
    
    # Diff
    diff_lines = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile="avant", tofile="après", lineterm=""
    ))
    
    accepted = sum(1 for d in decisions if d["accepted"])
    rejected = sum(1 for d in decisions if not d["accepted"])
    
    return {
        "status": "ok",
        "content": new_content,
        "diff": diff_lines,
        "accepted": accepted,
        "rejected": rejected,
        "message": f"✅ {accepted} amélioration(s) appliquée(s) (backup créé)",
    }


# === SEARCH ===

@app.get("/api/search")
def api_search(q: str, user: dict = Depends(get_current_user)):
    if len(q) < 2:
        raise HTTPException(400, "Requête trop courte")
    results = []
    for agent_id, agent in CONNECTED_AGENTS.items():
        for f in EDITABLE_FILES:
            filepath = agent["base_path"] / f["path"]
            if filepath.exists():
                try:
                    content = filepath.read_text(encoding="utf-8")
                    if q.lower() in content.lower():
                        lines = content.split("\n")
                        matches = [{"line": i+1, "text": l.strip()[:200]} for i, l in enumerate(lines) if q.lower() in l.lower()]
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


# === STATIC FILES ===
STATIC_DIR = Path(__file__).parent.parent / "static"

@app.get("/")
def serve_index():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "Agent Files Manager API v2.0"}

@app.get("/{path:path}")
def serve_static(path: str):
    file = STATIC_DIR / path
    if file.exists() and file.is_file():
        return FileResponse(file)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9475)
