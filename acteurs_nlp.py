"""Interpréteur spaCy (règles, français) : phrase -> plan CRUD pour Personne / Organisation."""
import json
import re
import unicodedata
from functools import lru_cache

import spacy
from fastapi import HTTPException
from spacy.matcher import Matcher

if __package__:
    from .repository import SCHEMA, ancestors
    from .acteurs_repository import COLLECTIONS, ISSUES, check_type
else:
    from repository import SCHEMA, ancestors
    from acteurs_repository import COLLECTIONS, ISSUES, check_type

EXAMPLES = ('Affiche les techniciens ; Combien de personnes sans organisation ? ; '
            'Quels techniciens travaillent pour service_distribution_ariana ? ; '
            'Crée un technicien nomComplet="Ali Ben" travaillePour=service_distribution_ariana ; '
            'Supprime la personne id=tech_demo')

ACTIONS = {
    "read": ["affiche", "afficher", "liste", "lister", "montre", "montrer", "cherche", "chercher",
             "recherche", "rechercher", "trouve", "trouver", "donne", "voir"],
    "count": ["combien", "compte", "compter", "nombre de"],
    "create": ["ajoute", "ajouter", "cree", "creer", "enregistre", "enregistrer", "insere", "inserer"],
    "update": ["modifie", "modifier", "mets a jour", "mettre a jour", "met a jour", "change", "changer"],
    "delete": ["supprime", "supprimer", "efface", "effacer", "retire", "retirer", "enleve", "enlever"],
}
TABLES = {"personnes": ["personne", "personnes"],
          "organisations": ["organisation", "organisations", "societe", "societes", "structure", "structures"]}
STOP = ["de", "du", "des", "d'", "la", "le", "les", "l'"]
FILLERS = set(STOP) | {"un", "une", "tous", "toutes", "tout", "et", "avec", "svp", "s'il", "vous", "plait", "merci",
                       "moi", "me", "nous", "qui", "que", "quel", "quels", "quelle", "quelles", "est", "sont",
                       "a", "y", "il", "dans", "base", "au", "aux", "total", "en", "ont", "existe", "existent",
                       "d", "l", "-moi", "-nous"}  # « d' » seul et « montre-moi » : résidus du tokenizer français

# Clés de la forme « cle=valeur » : alias français en plus des noms RDF (insensibles à la casse).
KEYS = {"id": "id", "type": "type", "label": "label", "nom": "nomComplet", "identifiant": "identifiantPersonne",
        "organisation": "travaillePour", "employeur": "travaillePour", "etat": "etatService"}
KEYS.update({name.lower(): name for name in SCHEMA["properties"]})

# Tournures relationnelles : (propriété RDF, table probable, motif). La valeur va jusqu'à « sans / dont / et ».
END = r"(?=\s+(?:sans|dont|avec|et|ou)\b|[\s?.!]*$)"
ARTICLE = r"(?:(?:l'|le\s+|la\s+|les\s+)\s*)?(?:(?:organisation|societe)\s+)?"
RELATIONS = [
    ("travaillePour", "personnes", r"(?:\bqui\s+)?\b(?:travaille|travaillent|travaillant|employe|employes|employee|employees)"
                                   r"\s+(?:pour|chez|par|dans|au sein de)\s+" + ARTICLE + r"(.+?)" + END),
    ("emploiePersonne", "organisations", r"(?:\bqui\s+)?\b(?:emploie|emploient|employant)\s+(.+?)" + END),
    ("collaboreAvec", "organisations", r"(?:\bqui\s+)?\b(?:collabore|collaborent|collaborant)\s+avec\s+" + ARTICLE + r"(.+?)" + END),
    ("gere", "organisations", r"(?:\bqui\s+)?\b(?:gere|gerent|gerant)\s+(.+?)" + END),
    ("intervientSur", "personnes", r"(?:\bqui\s+)?\b(?:intervient|interviennent|intervenant)\s+sur\s+(.+?)" + END),
]
ISSUE_PATTERNS = {
    "sans_organisation": r"\bsans\s+(?:organisation|employeur|entreprise)s?\b",
    "sans_nom": r"\bsans\s+nom(?:\s+complet)?\b",
    "sans_identifiant": r"\bsans\s+identifiant\b",
    "sans_employe": r"\bsans\s+(?:employe|personnel|salarie|personne)s?\b",
    "sans_collaboration": r"\bsans\s+(?:collaboration|collaborateur|partenaire)s?\b",
}
SEARCH = r"\b(?:(?:nomme|appele)(?:e|s|es)?|contenant|contient|contiennent|a)\s+(.+?)[\s?.!]*$"


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower())
                   if unicodedata.category(c) != "Mn").replace("’", "'")


def words_of(name):
    return normalize(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)).split()


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", normalize(text)).strip("_")


@lru_cache(maxsize=1)
def pipeline():
    """Matcher spaCy : actions, tables, classes de l'ontologie (avec pluriels et « de/du/des ») et groupes."""
    language = spacy.blank("fr")
    matcher = Matcher(language.vocab)
    groups = {}

    def phrase(key, text):
        matcher.add(key, [[{"LOWER": t.lower_} for t in language.make_doc(text)]])

    for action, words in ACTIONS.items():
        for word in words:
            phrase("action:" + action, word)
    for table, words in TABLES.items():
        for word in words:
            phrase("table:" + table, word)

    classes = [c for c in SCHEMA["classes"] if any(r in ancestors(c) for r in COLLECTIONS.values())
               and c not in COLLECTIONS.values()]
    firsts = {}
    for name in classes:
        words = words_of(name)
        pattern = []
        for index, word in enumerate(words):
            if index:
                pattern.append({"LOWER": {"IN": STOP}, "OP": "*"})
            pattern.append({"LOWER": {"IN": [word, word + "s"]}})
        matcher.add("type:" + name, [pattern])
        firsts.setdefault(words[0], []).append(name)
    # « les responsables », « les usagers » : premier mot commun sans classe du même nom -> groupe de classes.
    for word, names in firsts.items():
        if not any(words_of(n) == [word] for n in names):
            groups["group:" + word] = names
            matcher.add("group:" + word, [[{"LOWER": {"IN": [word, word + "s"]}}]])
    return language, matcher, groups


class Sentence:
    """Phrase dont on « consomme » les morceaux reconnus ; ce qui reste doit être compris."""

    def __init__(self, prompt):
        normalized = normalize(prompt)
        # Les positions ne correspondent que si la normalisation conserve la longueur (cas courant).
        self.chars = list(prompt if len(normalized) == len(prompt) else normalized)

    @property
    def raw(self):
        return "".join(self.chars)

    @property
    def text(self):
        return normalize(self.raw)

    def take(self, pattern):
        """Cherche le motif, le retire de la phrase et renvoie ses groupes (casse et accents d'origine)."""
        raw = self.raw
        match = re.search(pattern, normalize(raw))
        if not match:
            return None
        self.blank(match.start(), match.end())
        return [raw[match.start(g):match.end(g)].strip().strip('"') for g in range(1, (match.re.groups or 0) + 1)]

    def blank(self, start, end):
        self.chars[start:end] = " " * (end - start)


def fail(reason=None):
    raise HTTPException(422, (reason + " " if reason else "Demande non reconnue. ") + "Exemples : " + EXAMPLES)


def coerce(name, raw):
    if raw == "[]":
        return []
    if name in SCHEMA["properties"] and SCHEMA["properties"][name]["ranges"] == ["boolean"] \
            and normalize(raw) in ("true", "false", "vrai", "faux"):
        return normalize(raw) in ("true", "vrai")
    return raw


def read_assignments(sentence, plan):
    """Valeurs explicites « cle=valeur » ; les guillemets autorisent les espaces."""
    pattern = r'\b(\w+)\s*(>=|<=|>|<|=)\s*("(?:\\.|[^"\\])*"|[^\s;,]+)'
    seen = set()
    for match in list(re.finditer(pattern, sentence.raw)):
        key, op, raw = match.groups()
        name = KEYS.get(key.lower())
        if not name or key.lower() in seen:
            fail(f"Champ inconnu ou répété : {key}.")
        seen.add(key.lower())
        try:
            value = json.loads(raw) if raw.startswith('"') else raw.rstrip(".?!")
        except ValueError:
            fail("Guillemets mal formés.")
        if name in ("id", "type", "label"):
            if op != "=":
                fail(f"{key} n'accepte que « = ».")
            plan[name] = value
        elif op == "=":
            plan["properties"][name] = coerce(name, value)
        else:
            plan["filters"].append({"property": name, "operator": op, "value": value})
        sentence.blank(match.start(), match.end())


def read_phrases(sentence, plan, hints):
    """Tournures françaises : relations, contrôles qualité, année de création, limite."""
    for prop, table, pattern in RELATIONS:
        found = sentence.take(pattern)
        if found:
            plan["filters"].append({"property": prop, "operator": "=", "value": found[-1]})
            hints.append(table)
    for key, pattern in ISSUE_PATTERNS.items():
        if sentence.take(pattern) is not None:
            plan["issue"] = key
    year = (r"(?:\bannee\s+(?:de\s+)?creation|\bcree[es]?s?)\s+(superieure?\s+a|inferieure?\s+a|egale?\s+a|apres|avant|en)"
            r"\s+(\d{4})\b")
    found = sentence.take(year)
    if found:
        word = normalize(found[0])
        op = ">" if word.startswith(("superieur", "apres")) else "<" if word.startswith(("inferieur", "avant")) else "="
        plan["filters"].append({"property": "anneeCreation", "operator": op, "value": found[1]})
        hints.append("organisations")
    found = sentence.take(r"\b(?:les\s+)?(\d{1,3})\s+premier(?:e)?s?\b") or sentence.take(r"\b(?:top|limite)\s+(\d{1,3})\b")
    if found:
        plan["limit"] = int(found[0])
    quoted = sentence.take(r'"([^"]+)"')
    if quoted:
        plan["search"] = quoted[0]


def translate(prompt):
    language, matcher, groups = pipeline()
    plan = {"properties": {}, "filters": []}
    sentence, hints = Sentence(prompt), []
    read_assignments(sentence, plan)
    read_phrases(sentence, plan, hints)

    # Vocabulaire : on garde les expressions les plus longues, sans chevauchement.
    doc = language(sentence.text)
    priority = lambda key: 0 if key.startswith(("type:", "group:")) else 1
    matches = sorted(matcher(doc), key=lambda m: (m[2] - m[1], -priority(language.vocab.strings[m[0]])), reverse=True)
    used, found = set(), []
    for match_id, start, end in matches:
        if not used.intersection(range(start, end)):
            used.update(range(start, end))
            found.append(language.vocab.strings[match_id].split(":", 1))
            sentence.blank(doc[start].idx, doc[end - 1].idx + len(doc[end - 1].text))

    actions = {value for kind, value in found if kind == "action"}
    if len(actions) > 1:
        fail("Plusieurs actions détectées (" + ", ".join(sorted(actions)) + ").")

    types = {v for k, v in found if k == "type"}
    for key in (f"group:{v}" for k, v in found if k == "group"):
        types.update(groups[key])
    if plan.get("type"):
        types = {plan.pop("type")}
    types = {t for t in types if not any(o != t and o in ancestors(t) for o in types)}

    owners = {c for t in types for c, root in COLLECTIONS.items() if root in ancestors(t)}
    owners |= {v for k, v in found if k == "table"}
    if plan.get("issue"):
        owners.add(ISSUES[plan["issue"]][0])
    if not owners and hints:
        owners.add(hints[0])
    if not owners:
        fail("Précisez s'il s'agit de personnes ou d'organisations.")
    if len(owners) > 1:
        fail("Demande ambiguë : personnes et organisations sont mélangées.")
    collection = owners.pop()
    for t in types:
        check_type(collection, t)
    plan.update(collection=collection, action=actions.pop() if actions else "read",
                types=sorted(types) or None)

    # Recherche libre (« à Ariana », « nommé Salma »), ou nom de la ressource à créer.
    found_search = sentence.take(SEARCH)
    if found_search:
        plan["search"] = found_search[0]
    words = [t.text for t in language(sentence.raw) if not t.is_space and not t.is_punct]
    name = plan.pop("search", None) if plan["action"] == "create" else None
    if plan["action"] == "create":
        # Les mots restants forment le nom (casse d'origine) ; on retire seulement les mots vides aux extrémités.
        while words and normalize(words[0]) in FILLERS:
            words.pop(0)
        while words and normalize(words[-1]) in FILLERS:
            words.pop()
        name = " ".join(([name] if name else []) + words) or None
    else:
        unknown = [w for w in words if normalize(w) not in FILLERS]
        if unknown:
            fail("Mots non compris : « " + " ".join(unknown) + " ».")
    return finish(plan, name)


def finish(plan, name):
    action, collection, notes = plan["action"], plan["collection"], []
    if action in ("read", "count"):
        if plan.get("label"):
            if plan.get("search"):
                fail("Utilisez soit label=, soit une recherche libre.")
            plan["search"] = plan.pop("label")
        for key, value in plan.pop("properties").items():
            plan["filters"].append({"property": key, "operator": "=", "value": value})
        if action == "count":
            plan.pop("limit", None)
    else:
        if plan["filters"] or plan.get("issue") or plan.get("limit") or plan.get("search"):
            fail("Les filtres et recherches ne s'appliquent qu'à une lecture.")
        if action == "create":
            if len(plan["types"] or []) > 1:
                fail("Classe ambiguë : précisez type=NomDeClasse.")
            plan["type"] = (plan["types"] or [COLLECTIONS[collection]])[0]
            if name:
                field = "nomComplet" if collection == "personnes" else "label"
                if field == "label":
                    plan.setdefault("label", name)
                else:
                    plan["properties"].setdefault("nomComplet", name)
            title = plan.get("label") or plan["properties"].get("nomComplet")
            if not plan.get("id"):
                if not title:
                    fail("Précisez un nom ou id=...")
                plan["id"] = slug(title)
                notes.append("Identifiant généré : " + plan["id"])
            if not plan.get("label"):
                plan["label"] = title or plan["id"].replace("_", " ")
                notes.append("Libellé déduit : " + plan["label"])
        elif not plan.get("id"):
            fail("Un id=... explicite est obligatoire pour modifier ou supprimer.")
        if action == "update" and not (plan["properties"] or "label" in plan):
            fail("Rien à modifier : ajoutez champ=valeur.")
        if action == "delete" and (plan["properties"] or "label" in plan):
            fail("Une suppression ne prend que id=...")
        plan.pop("types", None)
    plan = {k: v for k, v in plan.items() if v not in (None, [], {})}
    plan["notes"] = notes
    return plan


def explain(plan):
    """Résumé en français de ce que l'interpréteur a compris."""
    titles = {"read": "Lister", "count": "Compter", "create": "Créer", "update": "Modifier", "delete": "Supprimer"}
    lines = [f"Action : {titles[plan['action']]}", f"Table : {plan['collection']}"]
    if plan.get("types"):
        lines.append("Classe : " + ", ".join(plan["types"]) + " (sous-classes incluses)")
    if plan.get("type"):
        lines.append("Classe : " + plan["type"])
    if plan.get("id"):
        lines.append("Identifiant : " + plan["id"])
    if plan.get("search"):
        lines.append(f"Recherche : « {plan['search']} »")
    if plan.get("issue"):
        lines.append("Contrôle : " + ISSUES[plan["issue"]][1])
    lines += [f"Filtre : {f['property']} {f['operator']} {f['value']}" for f in plan.get("filters", [])]
    if plan.get("label"):
        lines.append(f"Libellé : {plan['label']}")
    lines += [f"Champ : {k} = {v}" for k, v in (plan.get("properties") or {}).items()]
    if plan.get("limit"):
        lines.append(f"Limite : {plan['limit']}")
    return lines + plan.get("notes", [])
