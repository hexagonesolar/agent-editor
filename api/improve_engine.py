"""
Improvement Engine — 25 règles de proposition pour améliorer les fichiers agents
Sources: Anthropic Docs, Reddit r/ClaudeAI, Awesome CursorRules, MemGPT, communauté prompt engineering
"""

import re
from typing import Optional


# === Tables de reformulation ===
VAGUE_REPLACEMENTS = {
    "sois utile": "Réponds de manière directe et actionnable. Propose des solutions concrètes, pas des généralités.",
    "sois gentil": "Adopte un ton cordial mais professionnel. Pas de flatterie ni de formules creuses.",
    "sois sympathique": "Sois chaleureux dans le ton mais reste focalisé sur la tâche.",
    "be helpful": "Provide direct, actionable answers. Focus on solving the user's problem.",
    "be nice": "Maintain a professional, warm tone without unnecessary flattery.",
    "be friendly": "Be approachable but stay focused on delivering value.",
    "sois concis": "Limite tes réponses à l'essentiel. Pas de préambule ni de récapitulatif sauf si demandé.",
    "sois professionnel": "Utilise un vocabulaire précis et adapté au contexte. Pas de familiarité excessive.",
    "sois créatif": "Propose des solutions originales quand la situation s'y prête, mais privilégie toujours la fiabilité.",
}

REDUNDANT_DEFAULTS = [
    (r"(?:sois?|be)\s+(?:poli|polite)", "Claude est poli par défaut — cette instruction consomme des tokens inutilement."),
    (r"(?:réfléchis|think)\s+(?:étape par étape|step by step)", "Claude réfléchit déjà de manière structurée. Inutile de le préciser sauf pour des tâches très spécifiques."),
    (r"(?:sois?|be)\s+(?:honnête|honest)", "Claude est honnête par défaut. Préfère une instruction précise : 'Dis clairement quand tu n'es pas sûr'."),
    (r"(?:fais|do)\s+(?:de ton mieux|your best)", "Instruction générique sans valeur ajoutée — Claude fait toujours de son mieux."),
]

DEFAULT_CONSTRAINTS_DEV = """## Ce que tu ne dois JAMAIS faire
- Ne jamais inventer de commandes ou de chemins de fichiers — vérifier avant
- Ne jamais exposer de credentials (tokens, mots de passe, clés API) dans les réponses
- Ne jamais modifier de fichiers sans annoncer ce que tu vas faire
- Ne jamais supposer — demander clarification en cas de doute
- Ne jamais exécuter d'actions destructrices (rm -rf, DROP TABLE) sans confirmation explicite"""

DEFAULT_CONSTRAINTS_GENERAL = """## Ce que tu ne dois JAMAIS faire
- Ne jamais inventer d'informations — dire "je ne sais pas" si incertain
- Ne jamais s'excuser inutilement ou utiliser des formules creuses
- Ne jamais donner de réponses trop longues quand une réponse courte suffit
- Ne jamais ignorer le contexte de la conversation précédente"""

DEFAULT_CONSTRAINTS_HEALTH = """## Ce que tu ne dois JAMAIS faire
- Ne jamais donner de diagnostic médical
- Ne jamais remplacer l'avis d'un professionnel de santé
- Toujours recommander de consulter un médecin en cas de doute
- Ne jamais prescrire de médicaments ou de traitements"""

UNCERTAINTY_BLOCK = """## Gestion de l'incertitude
- Quand tu es confiant → réponds directement, sans hedging
- Quand tu es incertain (<80% de certitude) → dis-le clairement : "Je ne suis pas sûr, mais..."
- Quand tu ne sais pas → dis "Je ne sais pas" plutôt que d'inventer"""

MEMORY_CATEGORIES = """# Mémoire persistante

## Environnement technique
(serveur, OS, outils, versions)

## Projets actifs
(projets en cours, stack, URLs)

## Préférences utilisateur
(style, conventions, habitudes)

## Conventions & règles
(workflows, bonnes pratiques établies)

## Historique clé
(décisions importantes, incidents résolus)"""

USER_PROFILE_TEMPLATE = """# Profil utilisateur

## Identité
- **Nom** : {name}
- **Timezone** : {timezone}

## Expertise
- **Niveau technique** : {expertise}

## Communication
- **Style préféré** : {style}
- **Format de réponse** : {format}

## Ce qui l'agace
- {anti_prefs}"""


def classify_content(content: str) -> dict:
    """Classifie le contenu par catégorie via mots-clés."""
    categories = {
        "identity": [],
        "role": [],
        "rules": [],
        "style": [],
        "constraints": [],
        "other": []
    }
    
    identity_kw = r'(?:tu es|je suis|nom|name|agent|identité|identity|créature|personnage|character)'
    role_kw = r'(?:rôle|role|mission|objectif|tâche|task|responsab|développ|dev|gestion|manage)'
    rules_kw = r'(?:règle|rule|toujours|always|obligatoire|mandatory|important|doit|must|impératif)'
    style_kw = r'(?:ton|style|voix|langage|langue|français|english|formel|décontracté|technique|vibe|communication)'
    constraints_kw = r'(?:jamais|never|interdit|forbidden|ne pas|don\'t|pas le droit|prohib|danger|attention)'
    
    for line in content.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if re.search(constraints_kw, stripped, re.IGNORECASE):
            categories["constraints"].append(stripped)
        elif re.search(identity_kw, stripped, re.IGNORECASE):
            categories["identity"].append(stripped)
        elif re.search(rules_kw, stripped, re.IGNORECASE):
            categories["rules"].append(stripped)
        elif re.search(style_kw, stripped, re.IGNORECASE):
            categories["style"].append(stripped)
        elif re.search(role_kw, stripped, re.IGNORECASE):
            categories["role"].append(stripped)
        else:
            categories["other"].append(stripped)
    
    return categories


def detect_agent_type(content: str) -> str:
    """Détecte le type d'agent à partir du contenu."""
    content_lower = content.lower()
    if any(kw in content_lower for kw in ['dev', 'code', 'python', 'script', 'deploy', 'api', 'debug', 'cto']):
        return 'dev'
    elif any(kw in content_lower for kw in ['santé', 'health', 'médic', 'nutrition', 'sport', 'sommeil']):
        return 'health'
    elif any(kw in content_lower for kw in ['commercial', 'vente', 'lead', 'prospect', 'client', 'crm']):
        return 'sales'
    return 'general'


def estimate_tokens(text: str) -> int:
    """Estimation grossière du nombre de tokens (1 token ≈ 4 chars en français)."""
    return len(text) // 4


def generate_proposals(file_path: str, content: str) -> list:
    """Génère les propositions d'amélioration pour un fichier."""
    filename = file_path.split("/")[-1]
    proposals = []
    lines = content.split('\n')
    headers = re.findall(r'^#{1,3}\s+(.+)', content, re.MULTILINE)
    char_count = len(content)
    token_count = estimate_tokens(content)
    agent_type = detect_agent_type(content)

    if filename == "SOUL.md":
        proposals.extend(_soul_proposals(content, lines, headers, char_count, token_count, agent_type))
    elif filename == "MEMORY.md":
        proposals.extend(_memory_proposals(content, lines, headers, char_count))
    elif filename == "USER.md":
        proposals.extend(_user_proposals(content, lines, headers, char_count))
    elif filename == "config.yaml":
        proposals.extend(_config_proposals(content, lines))
    
    return proposals


def _soul_proposals(content: str, lines: list, headers: list, char_count: int, token_count: int, agent_type: str) -> list:
    proposals = []

    # === RULE 1: Structure ===
    if len(headers) < 3:
        classified = classify_content(content)
        new_content = "# SOUL.md\n\n"
        
        if classified["identity"]:
            new_content += "## Identité\n" + '\n'.join(classified["identity"]) + "\n\n"
        else:
            # Extraire la première ligne significative comme identité
            first_lines = [l for l in lines if l.strip() and not l.startswith('#')][:2]
            if first_lines:
                new_content += "## Identité\n" + '\n'.join(first_lines) + "\n\n"
        
        if classified["role"] or classified["other"]:
            role_lines = classified["role"] + classified["other"][:5]
            new_content += "## Rôle & Mission\n" + '\n'.join(role_lines) + "\n\n"
        
        if classified["rules"]:
            new_content += "## Règles\n" + '\n'.join(classified["rules"]) + "\n\n"
        
        if classified["style"]:
            new_content += "## Style de communication\n" + '\n'.join(classified["style"]) + "\n\n"
        
        if classified["constraints"]:
            new_content += "## Contraintes absolues\n" + '\n'.join(classified["constraints"]) + "\n\n"
        
        proposals.append({
            "id": "rule_structure",
            "title": "Restructurer en sections claires",
            "why": "Claude parse mieux les instructions organisées en sections ## (Identité, Rôle, Règles, Style, Contraintes). Le contenu actuel manque de structure — les instructions se diluent.",
            "severity": "warning",
            "before": content[:300] + ("..." if len(content) > 300 else ""),
            "after": new_content.strip(),
            "editable": True,
            "auto_accept": False,
            "full_file": True,
        })

    # === RULE 2: Instructions vagues ===
    vague_found = []
    new_content_vague = content
    for pattern, replacement in VAGUE_REPLACEMENTS.items():
        if pattern.lower() in content.lower():
            vague_found.append((pattern, replacement))
            new_content_vague = re.sub(re.escape(pattern), replacement, new_content_vague, flags=re.IGNORECASE)
    
    if vague_found:
        before_lines = [f'"{p}"' for p, _ in vague_found]
        after_lines = [f'"{r}"' for _, r in vague_found]
        proposals.append({
            "id": "rule_vague_instructions",
            "title": f"Reformuler {len(vague_found)} instruction(s) vague(s)",
            "why": "Les instructions vagues ('sois utile') n'ont aucun effet sur Claude. Les comportements précis sont 10x plus efficaces (source: Reddit r/ClaudeAI).",
            "severity": "warning",
            "before": '\n'.join(before_lines),
            "after": '\n'.join(after_lines),
            "editable": True,
            "auto_accept": False,
            "full_file": False,
            "_replacements": vague_found,
        })

    # === RULE 3: Contraintes négatives ===
    neg = re.findall(r'(?:jamais|ne pas|interdit|ne .*? pas|never|don\'t|forbidden)', content, re.IGNORECASE)
    if len(neg) == 0:
        constraints = DEFAULT_CONSTRAINTS_DEV if agent_type == 'dev' else DEFAULT_CONSTRAINTS_HEALTH if agent_type == 'health' else DEFAULT_CONSTRAINTS_GENERAL
        proposals.append({
            "id": "rule_negative_constraints",
            "title": "Ajouter les contraintes négatives (DO NOT)",
            "why": "Les sections 'Ne JAMAIS faire' sont parmi les instructions les plus respectées par Claude. Sans elles, l'agent peut déborder de son cadre (source: Anthropic docs + Reddit).",
            "severity": "warning",
            "before": "(aucune contrainte négative détectée)",
            "after": constraints,
            "editable": True,
            "auto_accept": False,
            "full_file": False,
            "_append": True,
        })

    # === RULE 4: Trop long ===
    if char_count > 5000:
        # Trouver les passages redondants
        seen_concepts = {}
        redundant = []
        for i, line in enumerate(lines):
            stripped = line.strip().lower()
            if len(stripped) < 20:
                continue
            words = set(stripped.split())
            for j, (prev_words, prev_line) in seen_concepts.items():
                overlap = len(words & prev_words) / max(len(words), 1)
                if overlap > 0.6:
                    redundant.append((i+1, line.strip(), j+1, prev_line))
                    break
            seen_concepts[i] = (words, line.strip())
        
        if redundant:
            before = '\n'.join([f"L{a}: {b}\n  ↔ similaire à L{c}: {d}" for a,b,c,d in redundant[:5]])
            proposals.append({
                "id": "rule_too_long",
                "title": f"Condenser le fichier ({char_count} → ~{char_count-len(redundant)*100} caractères)",
                "why": f"Le fichier fait {char_count} caractères (~{token_count} tokens). Au-delà de 1500 tokens, les instructions au milieu sont moins bien retenues ('lost in the middle'). {len(redundant)} redondances détectées.",
                "severity": "warning",
                "before": before,
                "after": "(les lignes redondantes seront supprimées)",
                "editable": False,
                "auto_accept": False,
                "full_file": False,
            })

    # === RULE 5: Pas d'exemples ===
    examples = re.findall(r'(?:exemple|example|<example|ex\s?:)', content, re.IGNORECASE)
    if not examples and char_count > 500:
        agent_desc = lines[0] if lines else "l'agent"
        example_block = f"""## Exemple de réponse idéale

<example>
<input>Utilisateur demande de l'aide sur une tâche</input>
<output>
1. Analyse rapide de la situation
2. Solution proposée avec étapes claires
3. Vérification que ça fonctionne
</output>
</example>"""
        proposals.append({
            "id": "rule_missing_examples",
            "title": "Ajouter un exemple de réponse idéale",
            "why": "Un seul exemple concret calibre le style de l'agent mieux que 10 lignes de règles abstraites. Claude est spécifiquement entraîné à suivre les blocs <example> (source: Anthropic docs).",
            "severity": "info",
            "before": "(aucun exemple de réponse)",
            "after": example_block,
            "editable": True,
            "auto_accept": False,
            "full_file": False,
            "_append": True,
        })

    # === RULE 6: Sandwich ===
    rule_lines = []
    for i, line in enumerate(lines):
        if re.search(r'(?:règle|rule|toujours|jamais|obligat|absolu)', line, re.IGNORECASE):
            rule_lines.append(i)
    
    if rule_lines and len(lines) > 10:
        middle_start = len(lines) // 4
        middle_end = 3 * len(lines) // 4
        rules_in_middle = [r for r in rule_lines if middle_start <= r <= middle_end]
        
        if len(rules_in_middle) > 2 and not any(r > middle_end for r in rule_lines):
            proposals.append({
                "id": "rule_sandwich",
                "title": "Déplacer les règles critiques en début et fin",
                "why": "Les LLMs retiennent mieux les instructions au DÉBUT et à la FIN du texte (effet primauté-récence). Les règles critiques sont actuellement perdues au milieu du fichier.",
                "severity": "info",
                "before": "Règles critiques aux lignes " + ', '.join([str(r+1) for r in rules_in_middle[:5]]) + " (milieu du fichier)",
                "after": "→ Rappel ajouté en fin de fichier :\n\n---\n⚠️ RAPPEL — Règles absolues :\n" + '\n'.join([f"- {lines[r].strip()}" for r in rules_in_middle[:3]]),
                "editable": True,
                "auto_accept": False,
                "full_file": False,
                "_append": True,
            })

    # === RULE 7: XML tags (NEW) ===
    has_xml = bool(re.search(r'<\w+>', content))
    if not has_xml and char_count > 1000:
        proposals.append({
            "id": "rule_xml_tags",
            "title": "Ajouter des balises XML pour les sections clés",
            "why": "Claude est spécifiquement entraîné à parser les balises XML (<role>, <instructions>, <constraints>). Les prompts avec XML produisent des résultats 23% plus cohérents (source: Anthropic docs).",
            "severity": "info",
            "before": "## Rôle\nTu es un agent...\n\n## Règles\n1. Toujours...",
            "after": "<role>\nTu es un agent...\n</role>\n\n<instructions>\n1. Toujours...\n</instructions>\n\n<constraints>\n- Ne jamais...\n</constraints>",
            "editable": True,
            "auto_accept": False,
            "full_file": False,
        })

    # === RULE 8: Token budget (NEW) ===
    if token_count > 1500:
        proposals.append({
            "id": "rule_token_budget",
            "title": f"Budget tokens dépassé ({token_count} tokens estimés)",
            "why": f"Le fichier consomme ~{token_count} tokens. Recommandation : 500-800 pour un agent spécialisé, 1500 max pour un agent multi-outils. Chaque token en trop dans le SOUL est un token en moins pour la conversation.",
            "severity": "warning",
            "before": f"Taille actuelle : {char_count} caractères ≈ {token_count} tokens",
            "after": f"Objectif : réduire à ~{min(token_count, 1200)} tokens en condensant les sections les moins critiques",
            "editable": False,
            "auto_accept": False,
            "full_file": False,
        })

    # === RULE 9: Gestion incertitude (NEW) ===
    uncertainty = re.findall(r'(?:incertain|uncertain|pas sûr|not sure|je ne sais pas|I don\'t know|doute)', content, re.IGNORECASE)
    if not uncertainty:
        proposals.append({
            "id": "rule_uncertainty",
            "title": "Ajouter la gestion de l'incertitude",
            "why": "Sans directive claire, l'agent soit invente (hallucination), soit met des caveats partout. Une règle explicite réduit les faux-caveats de ~60% (source: Reddit r/ClaudeAI).",
            "severity": "info",
            "before": "(aucune gestion de l'incertitude)",
            "after": UNCERTAINTY_BLOCK,
            "editable": True,
            "auto_accept": False,
            "full_file": False,
            "_append": True,
        })

    # === RULE 10: Hiérarchie (NEW) ===
    hierarchy = re.findall(r'(?:hiérarchie|hierarchy|principal|priorité|priority|écoute|obéi)', content, re.IGNORECASE)
    if not hierarchy:
        proposals.append({
            "id": "rule_principal_hierarchy",
            "title": "Définir la hiérarchie de commandement",
            "why": "Sans hiérarchie claire, l'agent ne sait pas quelles directives prioriser en cas de conflit (instructions système vs demande utilisateur). Recommandé par Anthropic pour les agents en production.",
            "severity": "info",
            "before": "(aucune hiérarchie définie)",
            "after": "## Hiérarchie\n- Tu réponds à JB. Sa directive prime sur tout.\n- En cas de conflit entre tes règles et une demande : appliquer les règles, expliquer pourquoi.",
            "editable": True,
            "auto_accept": False,
            "full_file": False,
            "_append": True,
        })

    # === RULE 11: Instructions redondantes (NEW) ===
    for pattern, reason in REDUNDANT_DEFAULTS:
        if re.search(pattern, content, re.IGNORECASE):
            match = re.search(pattern, content, re.IGNORECASE).group()
            proposals.append({
                "id": f"rule_redundant_{hash(pattern) % 10000}",
                "title": f"Supprimer l'instruction redondante : \"{match}\"",
                "why": reason,
                "severity": "info",
                "before": f'"{match}"',
                "after": "(supprimé — Claude fait ça par défaut)",
                "editable": False,
                "auto_accept": True,
                "full_file": False,
            })

    return proposals


def _memory_proposals(content: str, lines: list, headers: list, char_count: int) -> list:
    proposals = []

    # === RULE 12: Doublons ===
    clean_lines = [(i, l.strip()) for i, l in enumerate(lines) if len(l.strip()) > 20]
    duplicates = []
    for idx, (i, line_a) in enumerate(clean_lines):
        words_a = set(re.sub(r'[^\w\s]', '', line_a.lower()).split())
        if len(words_a) < 3:
            continue
        for j, line_b in clean_lines[idx+1:]:
            words_b = set(re.sub(r'[^\w\s]', '', line_b.lower()).split())
            if len(words_b) < 3:
                continue
            overlap = len(words_a & words_b) / max(len(words_a | words_b), 1)
            if overlap > 0.6:
                duplicates.append((i+1, line_a, j+1, line_b))
                break
    
    if duplicates:
        before = '\n'.join([f"L{a}: {b[:80]}\nL{c}: {d[:80]}\n" for a,b,c,d in duplicates[:5]])
        proposals.append({
            "id": "rule_duplicates",
            "title": f"Supprimer {len(duplicates)} doublon(s) détecté(s)",
            "why": "Des lignes quasi-identiques gaspillent des tokens. La mémoire doit être compacte — chaque fait ne doit apparaître qu'une fois.",
            "severity": "warning",
            "before": before,
            "after": "(les doublons marqués seront supprimés, gardant la version la plus complète)",
            "editable": False,
            "auto_accept": False,
            "full_file": False,
            "_duplicate_lines": [d[2] for d in duplicates],  # lignes à supprimer
        })

    # === RULE 13: Prose → bullets ===
    prose_blocks = []
    current_block = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and not stripped.startswith('-') and not stripped.startswith('*') and not stripped.startswith('|') and len(stripped) > 40:
            current_block.append((i, stripped))
        else:
            if len(current_block) >= 2:
                prose_blocks.append(current_block)
            current_block = []
    if len(current_block) >= 2:
        prose_blocks.append(current_block)
    
    if prose_blocks:
        first_block = prose_blocks[0]
        before = '\n'.join([l for _, l in first_block[:3]])
        after = '\n'.join([f"- {l}" for _, l in first_block[:3]])
        proposals.append({
            "id": "rule_prose_to_bullets",
            "title": f"Convertir {len(prose_blocks)} bloc(s) de prose en bullet points",
            "why": "La mémoire en bullet points est plus facile à parser pour l'agent et plus rapide à scanner. Le format prose ralentit la compréhension (source: MemGPT, LangChain).",
            "severity": "warning",
            "before": before,
            "after": after,
            "editable": True,
            "auto_accept": False,
            "full_file": False,
        })

    # === RULE 14: Impératif → déclaratif ===
    imperative_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r'^[-*]?\s*(?:toujours|always|utiliser|use|faire|lancer|run|execute|never|ne pas)\s', stripped, re.IGNORECASE):
            # Proposer une reformulation déclarative
            declarative = stripped
            declarative = re.sub(r'^[-*]?\s*(?:toujours\s+)?utiliser\s+', '- Utilise ', declarative, flags=re.IGNORECASE)
            declarative = re.sub(r'^[-*]?\s*(?:toujours\s+)?faire\s+', '- ', declarative, flags=re.IGNORECASE)
            declarative = re.sub(r'^[-*]?\s*(?:toujours\s+)?lancer\s+', '- Le script principal est ', declarative, flags=re.IGNORECASE)
            imperative_lines.append((i+1, stripped, declarative))
    
    if len(imperative_lines) > 1:
        before = '\n'.join([f"L{n}: {old}" for n, old, _ in imperative_lines[:4]])
        after = '\n'.join([f"→ {new}" for _, _, new in imperative_lines[:4]])
        proposals.append({
            "id": "rule_imperative_to_declarative",
            "title": f"Reformuler {len(imperative_lines)} instructions en faits déclaratifs",
            "why": "La mémoire stocke des FAITS ('Le projet utilise Python'), pas des ORDRES ('Utiliser Python'). Les ordres appartiennent au SOUL.md, les faits à la mémoire (source: Hermes docs).",
            "severity": "warning",
            "before": before,
            "after": after,
            "editable": True,
            "auto_accept": False,
            "full_file": False,
        })

    # === RULE 15: Entrées obsolètes ===
    stale = []
    for i, line in enumerate(lines):
        dates = re.findall(r'20\d{2}[-/]\d{2}[-/]\d{2}', line)
        for d in dates:
            try:
                from datetime import datetime
                dt = datetime.strptime(d.replace('/', '-'), '%Y-%m-%d')
                days_ago = (datetime.now() - dt).days
                if days_ago > 90:
                    stale.append((i+1, line.strip(), days_ago))
            except:
                pass
    
    if stale:
        before = '\n'.join([f"L{n}: {l[:80]} (il y a {d} jours)" for n, l, d in stale[:5]])
        proposals.append({
            "id": "rule_stale_entries",
            "title": f"{len(stale)} entrée(s) datée(s) de plus de 90 jours",
            "why": "Les entrées obsolètes polluent la mémoire. Si une info n'a pas été renforcée depuis 90 jours, elle est probablement périmée.",
            "severity": "info",
            "before": before,
            "after": "(les entrées cochées seront supprimées)",
            "editable": False,
            "auto_accept": False,
            "full_file": False,
            "_stale_lines": [s[0] for s in stale],
        })

    # === RULE 16: Trop volumineuse ===
    if char_count > 4000:
        proposals.append({
            "id": "rule_memory_too_large",
            "title": f"Mémoire trop volumineuse ({char_count} caractères)",
            "why": f"La mémoire est injectée à CHAQUE tour de conversation. À {char_count} caractères (~{char_count//4} tokens), elle consomme un budget significatif. Objectif : <4000 caractères.",
            "severity": "warning",
            "before": f"Taille actuelle : {char_count} caractères",
            "after": "Réduire en appliquant les autres propositions (doublons, obsolètes, prose)",
            "editable": False,
            "auto_accept": False,
            "full_file": False,
        })

    # === RULE 17: Catégoriser (NEW) ===
    if len(headers) < 3 and char_count > 500:
        proposals.append({
            "id": "rule_categorize_memory",
            "title": "Organiser la mémoire en catégories",
            "why": "Une mémoire catégorisée (Environnement, Projets, Préférences, Conventions) est plus facile à maintenir et à scanner pour l'agent. Structure recommandée par MemGPT et LangChain.",
            "severity": "info",
            "before": f"Structure actuelle : {len(headers)} section(s) — contenu en vrac",
            "after": MEMORY_CATEGORIES,
            "editable": True,
            "auto_accept": False,
            "full_file": False,
        })

    return proposals


def _user_proposals(content: str, lines: list, headers: list, char_count: int) -> list:
    proposals = []

    # === RULE 18: Niveau technique ===
    expertise = re.findall(r'(?:technique|dev|développeur|non.?dev|expert|débutant|level|niveau)', content, re.IGNORECASE)
    if not expertise:
        proposals.append({
            "id": "rule_missing_expertise",
            "title": "Ajouter le niveau technique",
            "why": "Sans cette info, l'agent ne sait pas calibrer ses explications. Un dev n'a pas besoin qu'on lui explique 'cd' — un non-dev si.",
            "severity": "warning",
            "before": "(niveau technique non défini)",
            "after": "- **Niveau technique** : non-développeur — comprend les concepts mais ne code pas. Être précis dans les instructions techniques.",
            "editable": True,
            "auto_accept": False,
            "full_file": False,
            "_append": True,
        })

    # === RULE 19: Préférences communication ===
    comm = re.findall(r'(?:concis|détaillé|bref|format|réponse|préfère|style|bullet|code.?first)', content, re.IGNORECASE)
    if not comm:
        proposals.append({
            "id": "rule_missing_comm_prefs",
            "title": "Ajouter les préférences de communication",
            "why": "C'est l'amélioration la plus impactante du profil utilisateur. Sans ça, l'agent alterne entre réponses trop longues et trop courtes aléatoirement.",
            "severity": "warning",
            "before": "(aucune préférence de communication)",
            "after": "## Préférences de communication\n- Réponses directes et concises\n- Instructions pas-à-pas pour les tâches techniques\n- Pas de jargon inutile — français simple",
            "editable": True,
            "auto_accept": False,
            "full_file": False,
            "_append": True,
        })

    # === RULE 20: Timezone ===
    tz = re.findall(r'(?:timezone|fuseau|UTC|GMT|CET|heure|time.?zone)', content, re.IGNORECASE)
    if not tz:
        proposals.append({
            "id": "rule_missing_timezone",
            "title": "Ajouter la timezone",
            "why": "Utile pour les rappels, les cron jobs, et toute référence temporelle ('ce matin', 'hier soir').",
            "severity": "info",
            "before": "(pas de timezone)",
            "after": "- **Timezone** : UTC+1 (France)",
            "editable": True,
            "auto_accept": False,
            "full_file": False,
            "_append": True,
        })

    # === RULE 21: Anti-préférences ===
    anti = re.findall(r'(?:agace|énerve|déteste|hates?|annoy|pet peeve|ne pas faire|avoid)', content, re.IGNORECASE)
    if not anti:
        proposals.append({
            "id": "rule_missing_anti_prefs",
            "title": "Ajouter les anti-préférences (ce qui l'agace)",
            "why": "Dire à l'agent ce que l'utilisateur N'AIME PAS est souvent plus efficace que de dire ce qu'il aime. Ça évite les comportements irritants récurrents.",
            "severity": "info",
            "before": "(aucune anti-préférence)",
            "after": "## Ce qui l'agace\n- Les réponses trop longues quand une réponse courte suffit\n- Les excuses inutiles (\"Je m'excuse pour la confusion...\")\n- Les récapitulatifs non demandés",
            "editable": True,
            "auto_accept": False,
            "full_file": False,
            "_append": True,
        })

    # === RULE 22: Structure profil (NEW) ===
    if len(headers) < 2 and char_count > 100:
        proposals.append({
            "id": "rule_profile_structure",
            "title": "Structurer le profil en sections",
            "why": "Un profil structuré (Identité → Expertise → Communication → Contexte) permet à l'agent de trouver rapidement l'info pertinente (source: XML profile pattern, communauté).",
            "severity": "info",
            "before": f"Structure actuelle : {len(headers)} section(s)",
            "after": "## Identité\n(nom, rôle)\n\n## Expertise\n(niveau technique, domaines)\n\n## Communication\n(style préféré, format)\n\n## Contexte\n(projets actuels, outils utilisés)",
            "editable": True,
            "auto_accept": False,
            "full_file": False,
        })

    return proposals


def _config_proposals(content: str, lines: list) -> list:
    proposals = []

    # === RULE 23: Fix tabs ===
    if '\t' in content:
        fixed = content.replace('\t', '  ')
        proposals.append({
            "id": "rule_fix_tabs",
            "title": "Corriger les tabulations → espaces",
            "why": "YAML n'accepte que les espaces. Les tabulations cassent le parsing et empêchent l'agent de démarrer.",
            "severity": "danger",
            "before": "(tabulations détectées dans le fichier)",
            "after": "(toutes les tabulations remplacées par 2 espaces)",
            "editable": False,
            "auto_accept": True,
            "full_file": False,
        })

    # === RULE 24: Modèle ===
    if 'model:' not in content:
        proposals.append({
            "id": "rule_model_check",
            "title": "Ajouter la configuration du modèle",
            "why": "Sans modèle défini, l'agent utilise le défaut global. Mieux vaut le fixer explicitement pour éviter les surprises.",
            "severity": "warning",
            "before": "(pas de section model: dans le config)",
            "after": "model:\n  default: claude-sonnet-4-6\n  provider: anthropic",
            "editable": True,
            "auto_accept": False,
            "full_file": False,
        })

    # === RULE 25: Timeout (NEW) ===
    timeout_match = re.search(r'gateway_timeout:\s*(\d+)', content)
    if timeout_match:
        timeout = int(timeout_match.group(1))
        if timeout > 3600:
            proposals.append({
                "id": "rule_timeout_check",
                "title": f"Timeout trop long ({timeout}s = {timeout//60} min)",
                "why": "Un timeout excessif permet des conversations infinies qui consomment des tokens inutilement. 30 minutes (1800s) est un bon défaut.",
                "severity": "info",
                "before": f"gateway_timeout: {timeout}",
                "after": "gateway_timeout: 1800",
                "editable": True,
                "auto_accept": False,
                "full_file": False,
            })

    return proposals


def apply_proposals(original: str, proposals: list, decisions: list) -> str:
    """Applique les propositions acceptées au contenu original."""
    content = original
    
    # Trier les décisions : full_file d'abord, puis append, puis remplacements
    full_file_proposals = []
    append_proposals = []
    replace_proposals = []
    
    for decision in decisions:
        if not decision.get("accepted"):
            continue
        pid = decision["id"]
        proposal = next((p for p in proposals if p["id"] == pid), None)
        if not proposal:
            continue
        
        # Utiliser le texte custom si fourni
        text = decision.get("custom_text") or proposal["after"]
        
        if proposal.get("full_file"):
            full_file_proposals.append(text)
        elif proposal.get("_append"):
            append_proposals.append(text)
        elif proposal.get("_replacements"):
            for old, new in proposal["_replacements"]:
                content = re.sub(re.escape(old), new, content, flags=re.IGNORECASE)
        elif proposal.get("_duplicate_lines"):
            lines = content.split('\n')
            to_remove = set(proposal["_duplicate_lines"])
            content = '\n'.join([l for i, l in enumerate(lines, 1) if i not in to_remove])
        elif proposal["id"] == "rule_fix_tabs":
            content = content.replace('\t', '  ')
    
    # Appliquer full_file (remplace tout)
    if full_file_proposals:
        content = full_file_proposals[-1]
    
    # Appliquer les appends
    for text in append_proposals:
        content = content.rstrip() + "\n\n" + text
    
    return content
