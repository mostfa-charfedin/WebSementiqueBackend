"""Interpréteur français à règles spaCy, sans service NLP externe."""
import json
import re
import unicodedata
from functools import lru_cache

import spacy
from fastapi import HTTPException
from spacy.matcher import PhraseMatcher

if __package__:
    from .repository import SCHEMA, ROOTS, ancestors, valid_type
else:
    from repository import SCHEMA, ROOTS, ancestors, valid_type


def normalize(text):
    if text is None:
        return ""
    text = text.lower().replace("’", "'").replace("`", "'")
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).encode("ascii", "ignore").decode("ascii")


@lru_cache(maxsize=1)
def pipeline():
    # Le tokenizer français suffit : aucune installation de modèle à télécharger.
    language = spacy.blank("fr")
    matcher = PhraseMatcher(language.vocab, attr="LOWER")
    phrases = {
        "table:equipements": ["equipement", "equipements"],
        "table:informations": ["information", "informations"],
        "action:read": ["affiche", "afficher", "liste", "lister", "montre", "montrer", "cherche", "chercher", "trouve", "donne"],
        "action:create": ["ajoute", "ajouter", "cree", "creer"],
        "action:update": ["modifie", "modifier", "mets a jour", "mettre a jour"],
        "action:delete": ["supprime", "supprimer", "efface", "effacer"],
        "table:installations": ["installation", "installations", "centrale", "centrales", "site de production", "sites de production"],
        "table:reserves": ["reserve", "reserves", "réserve", "réserves", "stockage", "stockages"],
        "table:reseaux": ["reseau", "reseaux"],
        "table:infrastructures": ["infrastructure", "infrastructures"],
        "table:lieux": ["lieu", "lieux", "batiment", "batiments", "site", "sites", "emplacement", "emplacements"],
        "table:transports": ["transport", "transports", "acheminement", "acheminements", "livraison", "livraisons"],
    }
    aliases = {
        "Equipement": ["equipement", "equipements"],
        "Information": ["information", "informations"],
        "Capteur": ["capteur", "capteurs"],
        "CapteurCourant": ["capteur de courant", "capteurs de courant"],
        "CapteurTension": ["capteur de tension", "capteurs de tension"],
        "CapteurTemperature": ["capteur de temperature", "capteurs de temperature"],
        "CompteurIntelligent": ["compteur", "compteurs", "compteur intelligent", "compteurs intelligents"],
        "EquipementElectrique": ["equipement electrique", "equipements electriques"],
        "Mesure": ["mesure", "mesures"],
        "MesureElectrique": ["mesure electrique", "mesures electriques"],
        "MesureStockage": ["mesure de stockage", "mesures de stockage"],
        "Incident": ["incident", "incidents"],
        "IncidentMateriel": ["incident materiel", "incidents materiels"],
        "IncidentAlimentation": ["incident d'alimentation", "incidents d'alimentation"],
        "Installation": ["installation", "installations"],
        "SourceProduction": ["source de production", "sources de production", "centrale solaire", "centrale photovoltaique", "eolienne"],
        "SystemeStockage": ["systeme de stockage", "systemes de stockage", "batterie", "batteries", "stockage"],
        "Reserve": ["reserve", "reserves", "réserve", "réserves"],
        "ReserveExploitation": ["reserve d'exploitation", "réserve d'exploitation"],
        "ReserveDePuissance": ["reserve de puissance", "réserve de puissance"],
        "ReserveDeSecours": ["reserve de secours", "réserve de secours"],
        "ReseauElectrique": ["reseau electrique", "reseaux electriques"],
        "ReseauDistribution": ["reseau de distribution", "reseaux de distribution"],
        "ReseauTransport": ["reseau de transport", "reseaux de transport"],
        "ReseauCommunication": ["reseau de communication", "reseaux de communication"],
        "MicroReseau": ["micro reseau", "micro reseaux", "microreseau", "microreseaux"],
        "LigneElectrique": ["ligne", "lignes", "lignes electriques"],
        "LigneHauteTension": ["ligne haute tension", "lignes haute tension"],
        "LigneMoyenneTension": ["ligne moyenne tension", "lignes moyenne tension"],
        "LigneBasseTension": ["ligne basse tension", "lignes basse tension"],
        "Transformateur": ["transformateur", "transformateurs"],
        "PosteCommande": ["poste", "postes", "poste de commande", "postes de commande"],
        "Lieu": ["lieu", "lieux", "site", "sites"],
        "Batiment": ["batiment", "batiments", "immeuble", "immeubles"],
        "BatimentCommercial": ["batiment commercial", "batiments commerciaux"],
        "BatimentIndustriel": ["batiment industriel", "batiments industriels"],
        "BatimentResidentiel": ["batiment residentiel", "batiments residentiels"],
        "CommerceAvecRecharge": ["commerce avec recharge"],
        "AtelierAvecPilotageDeCharge": ["atelier avec pilotage", "atelier avec pilotage de charge"],
        "ChampPhotovoltaique": ["champ photovoltaique", "champs photovoltaiques"],
        "ParcEolienTerrestre": ["parc eolien", "parcs eoliens", "parc eolien terrestre"],
        "SiteProduction": ["site de production", "sites de production"],
        "SiteDistribution": ["site de distribution", "sites de distribution"],
        "Transport": ["transport", "transports"],
        "TransportElectricite": ["transport d'electricite", "transport electrique", "transports electriques"],
        "TransportMaintenance": ["transport de maintenance", "transport maintenance"],
        "TransportMateriel": ["transport de materiel", "transports de materiels", "transport materiel"],
        "AcheminementHauteTension": ["acheminement haute tension"],
        "Acheminement225kV": ["acheminement 225kv", "acheminement 225 kv"],
        "Acheminement90kV": ["acheminement 90kv", "acheminement 90 kv"],
        "AcheminementOutillage": ["acheminement outillage", "acheminement d'outillage"],
        "AcheminementPiecesDeRechange": ["acheminement pieces de rechange", "acheminement de pieces de rechange"],
        "LivraisonBatterie": ["livraison batterie", "livraison de batterie", "livraisons de batteries"],
        "LivraisonTransformateur": ["livraison transformateur", "livraison de transformateur"],
        "LivraisonEquipements": ["livraison equipement", "livraison equipements", "livraison d'equipements"],
        "DistributionLocale": ["distribution locale"],
        "Distribution30kV": ["distribution 30kv", "distribution 30 kv"],
        "Distribution230V": ["distribution 230v", "distribution 230 v"],
    }
    for name in SCHEMA["classes"]:
        if any(ancestors(name).intersection(roots) for roots in ROOTS.values()):
            words = normalize(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name))
            phrases["type:" + name] = [normalize(name), words] + aliases.get(name, [])
    for key, values in phrases.items():
        matcher.add(key, [language.make_doc(v) for v in values])
    return language, matcher


def fail():
    raise HTTPException(422, 'Demande non reconnue ou ambiguë. ')


def translate(prompt):
    language, matcher = pipeline()
    plan = {"properties": {}}
    # Masquer les valeurs avant la détection des intentions (ex. label="supprime").
    remaining = list(prompt)
    assignments = list(re.finditer(r'\b(\w+)\s*(>=|<=|>|<|=)\s*("(?:\\.|[^"\\])*"|[^\s;,]+)', prompt))
    seen = set()
    for match in assignments:
        key, op, raw = match.groups()
        if key in seen:
            fail()
        seen.add(key)
        try:
            value = json.loads(raw) if raw.startswith('"') else raw
        except ValueError:
            fail()
        if key in ["id", "type", "label"] and op == "=":
            plan[key] = value
        elif key in SCHEMA["properties"]:
            if op == "=":
                plan["properties"][key] = value
            else:
                plan.setdefault("filters", []).append({"property": key, "operator": op, "value": value})
        else:
            fail()
        remaining[match.start():match.end()] = " " * (match.end() - match.start())
    text = normalize("".join(remaining))
    doc = language(text)
    # Ne garder que les expressions les plus longues en cas de recouvrement.
    matches = sorted(matcher(doc), key=lambda m: m[2] - m[1], reverse=True)
    used, found = set(), []
    for key, start, end in matches:
        if not used.intersection(range(start, end)):
            used.update(range(start, end))
            found.append(language.vocab.strings[key].split(":", 1))
    actions = {v for k, v in found if k == "action"}
    if len(actions) != 1:
        fail()
    plan["action"] = actions.pop()
    types = {v for k, v in found if k == "type"}
    if plan.get("type"):
        types.add(plan["type"])
    # « transformateur type=Transformateur30kV400V » désigne la sous-classe.
    types = {t for t in types if not any(t != other and t in ancestors(other) for other in types)}
    if len(types) > 1:
        fail()
    if types:
        plan["type"] = types.pop()
    tables = {v for k, v in found if k == "table"}
    if plan.get("type"):
        tables.update(c for c, roots in ROOTS.items() if ancestors(plan["type"]).intersection(roots))
    if len(tables) != 1:
        fail()
    plan["collection"] = tables.pop()
    if plan.get("type"):
        valid_type(plan["collection"], plan["type"])

    # Recherche sur le libellé : « à Tunis », « contenant Tunis ».
    leftover = " ".join(token.text for i, token in enumerate(doc) if i not in used)
    # Filtres numériques en français, limités aux propriétés de ce module.
    numeric_names = {
        "tension nominale": "tensionNominaleV", "frequence nominale": "frequenceNominaleHz",
        "fiabilite": "niveauFiabilitePourcent", "longueur": "longueurKm",
        "tension d'entree": "tensionEntreeV", "tension de sortie": "tensionSortieV",
        "puissance nominale": "puissanceNominaleKVA", "rendement": "rendementPourcent",
        "surface": "surfaceM2", "superficie": "surfaceM2",
        "consommation": "consommationKWh",
        "annee de construction": "anneeConstruction", "annee": "anneeConstruction",
        "nombre d'etages": "nombreEtages", "nombre d'etage": "nombreEtages",
    }
    numeric_pattern = (r"(?:dont\s+)?(?:(?:la|le|une|un)\s+)?(" + "|".join(re.escape(k) for k in numeric_names)
                       + r")\s+(?:est\s+)?(superieur(?:e)? a|inferieur(?:e)? a|egal(?:e)? a|au moins|au plus)"
                       + r"\s+([+-]?\d+(?:[.,]\d+)?)(?:\s+(?:v|hz|km|kva|pourcent|%))?")
    numeric_matches = list(re.finditer(numeric_pattern, leftover))
    for match in reversed(numeric_matches):
        if plan["action"] != "read":
            fail()
        name, comparison, number = match.groups()
        op = ">" if comparison.startswith("superieur") else "<" if comparison.startswith("inferieur") else {"au moins": ">=", "au plus": "<="}.get(comparison, "=")
        plan.setdefault("filters", []).append({"property": numeric_names[name], "operator": op,
                                               "value": number.replace(",", ".")})
        leftover = leftover[:match.start()] + " " + leftover[match.end():]
    search = re.search(r'\b(?:a|contenant|nomme|nommee)\s+(.+?)\s*[?.!]*$', leftover)
    if search:
        if plan["action"] != "read":
            fail()
        # Reprendre la casse et les accents depuis la saisie originale.
        original = re.search(r'\b(?:à|a|contenant|nommé|nommée)\s+(.+?)\s*[?.!]*$', "".join(remaining), re.I)
        plan["search"] = (original.group(1) if original else search.group(1)).strip().strip('"')
        leftover = leftover[:search.start()]
    fillers = {"le", "la", "les", "un", "une", "des", "du", "de", "l'", "d'", "tous", "toutes", "et", "avec", "svp", "s'il", "vous", "plait"}
    if any(t.is_alpha and t.text not in fillers or (not t.is_alpha and not t.is_punct and not t.is_space)
           for t in language(leftover)):
        fail()
    if plan["action"] == "read":
        if "label" in plan:
            if "search" in plan:
                fail()
            plan["search"] = plan.pop("label")
        for key, value in plan.pop("properties").items():
            plan.setdefault("filters", []).append({"property": key, "operator": "=", "value": value})
    else:
        if not plan.get("id") or plan.get("filters"):
            fail()
        if plan["action"] == "create" and not plan.get("type"):
            fail()
        if plan["action"] == "update" and not (plan.get("properties") or "label" in plan):
            fail()
        if plan["action"] == "delete" and (plan.get("properties") or "label" in plan):
            fail()
    return plan
