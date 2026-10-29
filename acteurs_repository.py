"""Gestion des acteurs et des organisations : CRUD Personne / Organisation sur Fuseki."""
from fastapi import HTTPException
from rdflib import Literal

if __package__:
    from .repository import NAMESPACE, PREFIXES, SCHEMA, ancestors, iri, literal, term
else:
    from repository import NAMESPACE, PREFIXES, SCHEMA, ancestors, iri, literal, term

COLLECTIONS = {"personnes": "Personne", "organisations": "Organisation"}
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
RDFS_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"
NAMED_INDIVIDUAL = "<http://www.w3.org/2002/07/owl#NamedIndividual>"
OPERATORS = ["=", ">", "<", ">=", "<="]
NAMES = ("OPTIONAL { ?s rdfs:label ?lbl } OPTIONAL { ?s eg:nomComplet ?nom } "
         "OPTIONAL { ?s eg:identifiantPersonne ?ident }")

# Contrôles de qualité : clé -> (table, titre, condition SPARQL sur ?s).
# Les relations sont cherchées dans les deux sens (travaillePour / emploiePersonne ne sont pas synchronisées).
ISSUES = {
    "sans_nom": ("personnes", "Personnes sans nom complet",
                 "FILTER NOT EXISTS { ?s eg:nomComplet ?x }"),
    "sans_identifiant": ("personnes", "Personnes sans identifiant",
                         "FILTER NOT EXISTS { ?s eg:identifiantPersonne ?x }"),
    "sans_organisation": ("personnes", "Personnes sans organisation",
                          "FILTER NOT EXISTS { { ?s eg:travaillePour ?x } UNION { ?x eg:emploiePersonne ?s } }"),
    "sans_employe": ("organisations", "Organisations sans employé",
                     "FILTER NOT EXISTS { { ?s eg:emploiePersonne ?x } UNION { ?x eg:travaillePour ?s } }"),
    "sans_collaboration": ("organisations", "Organisations sans collaboration",
                           "FILTER NOT EXISTS { { ?s eg:collaboreAvec ?x } UNION { ?x eg:collaboreAvec ?s } }"),
}


def local(value):
    return value.removeprefix(NAMESPACE)


def check_type(collection, name):
    if name not in SCHEMA["classes"] or COLLECTIONS[collection] not in ancestors(name):
        raise HTTPException(422, f"Classe incompatible avec {collection} : {name}")
    return name


def scope(collection, types=None, subject="?s"):
    roots = [check_type(collection, t) for t in types] if types else [COLLECTIONS[collection]]
    return "VALUES ?root { " + " ".join("eg:" + r for r in roots) + " } " + f"{subject} rdf:type/rdfs:subClassOf* ?root ."


def where(collection, types=None, id=None, search=None, issue=None, filters=()):
    """Condition SPARQL qui lie ?s aux ressources demandées."""
    parts = [scope(collection, types)]
    if id:
        parts.append(f"VALUES ?s {{ {iri(id)} }}")
    terms = (search or "").lower().split()
    if terms:
        # Recherche multi-mots sur l'identifiant, le libellé, le nom complet et l'identifiant de personne.
        text = (f'LCASE(CONCAT(STRAFTER(STR(?s), "{NAMESPACE}"), " ", COALESCE(STR(?lbl), ""), " ", '
                'COALESCE(STR(?nom), ""), " ", COALESCE(STR(?ident), "")))')
        parts.append(NAMES + " FILTER(" + " && ".join(f"CONTAINS({text}, {literal(t)})" for t in terms) + ")")
    if issue:
        if issue not in ISSUES or ISSUES[issue][0] != collection:
            raise HTTPException(422, f"Contrôle inconnu pour {collection} : {issue}")
        parts.append(ISSUES[issue][2])
    for index, f in enumerate(filters):
        name, op, value = f["property"], f.get("operator", "="), f["value"]
        spec = SCHEMA["properties"].get(name)
        if not spec or op not in OPERATORS:
            raise HTTPException(422, f"Filtre non reconnu : {name}")
        var = f"?f{index}"
        if spec["kind"] == "ObjectProperty":
            if op != "=":
                raise HTTPException(422, f"{name} est une relation : seul « = » est accepté.")
            # La cible se désigne par son identifiant exact ou par un morceau de son libellé.
            needle = str(value).removeprefix(NAMESPACE).removeprefix("eg:").strip().lower()
            text = (f'LCASE(CONCAT(STRAFTER(STR({var}), "{NAMESPACE}"), " ", COALESCE(STR(?fl{index}), "")))')
            parts.append(f"?s eg:{name} {var} . OPTIONAL {{ {var} rdfs:label ?fl{index} }} "
                         f'FILTER(LCASE(STRAFTER(STR({var}), "{NAMESPACE}")) = {literal(needle)} || '
                         f'CONTAINS({text}, {literal(needle.replace("_", " "))}))')
        else:
            parts.append(f"?s eg:{name} {var} . FILTER({var} {op} {term(name, value)})")
    return " ".join(parts)


def shape(rows):
    """Regroupe les lignes ?s ?p ?o en ressources lisibles par le frontend."""
    items = {}
    for row in rows:
        uri = row["s"]["value"]
        item = items.setdefault(uri, {"id": local(uri), "uri": uri, "types": [], "label": None,
                                      "comment": None, "properties": {}})
        pred, obj = row["p"]["value"], row["o"]
        if pred == RDF_TYPE:
            if obj["value"].startswith(NAMESPACE):
                item["types"].append(local(obj["value"]))
        elif pred == RDFS_LABEL:
            item["label"] = obj["value"]
        elif pred == RDFS_COMMENT:
            item["comment"] = obj["value"]
        elif pred.startswith(NAMESPACE):
            value = local(obj["value"]) if obj["type"] == "uri" else obj["value"]
            item["properties"].setdefault(local(pred), []).append(value)
    for item in items.values():
        item["type"] = most_specific(item["types"])
        names = item["properties"].get("nomComplet")
        item["name"] = names[0] if names else item["label"] or item["id"]
    return list(items.values())


def most_specific(types):
    return max(types, key=lambda t: len(ancestors(t))) if types else None


def schema():
    """Classes et propriétés du module, pour générer les formulaires côté frontend."""
    properties = {}
    for name, spec in SCHEMA["properties"].items():
        relation = spec["kind"] == "ObjectProperty"
        properties[name] = {"kind": "relation" if relation else "data",
                            "datatype": None if relation else spec["ranges"][0],
                            "targets": spec["ranges"] if relation else []}
    collections = {}
    for collection, root in COLLECTIONS.items():
        classes = []
        for name in sorted(SCHEMA["classes"]):
            if root not in ancestors(name):
                continue
            parents = [p for p in SCHEMA["classes"][name] if root in ancestors(p)]
            classes.append({"name": name, "parent": parents[0] if parents else None,
                            "properties": [p for p, s in SCHEMA["properties"].items()
                                           if set(s["domains"]).issubset(ancestors(name))]})
        collections[collection] = {"root": root, "classes": classes}
    return {"namespace": NAMESPACE, "collections": collections, "properties": properties,
            "issues": {key: {"collection": c, "title": t} for key, (c, t, _) in ISSUES.items()}}


class Acteurs:
    def __init__(self, store):
        self.store = store

    def total(self, body):
        query = PREFIXES + f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ {body} }}"
        return int(self.store.query(query)["results"]["bindings"][0]["n"]["value"])

    # -- Exécution d'un plan (REST et NLP partagent le même chemin) ------------------------------
    def run(self, plan, execute=True):
        action = plan["action"]
        handler = {"read": self.read, "count": self.count}.get(action, self.write)
        return {"action": action, "collection": plan["collection"], "plan": plan, **handler(plan, execute)}

    def read(self, plan, execute=True):
        body = where(plan["collection"], plan.get("types"), plan.get("id"), plan.get("search"),
                     plan.get("issue"), plan.get("filters", []))
        limit = min(max(int(plan.get("limit") or 50), 1), 200)
        offset = max(int(plan.get("offset") or 0), 0)
        query = PREFIXES + f"""SELECT ?s ?p ?o WHERE {{
          {{ SELECT DISTINCT ?s WHERE {{ {body} }} ORDER BY ?s LIMIT {limit} OFFSET {offset} }}
          ?s ?p ?o .
        }} ORDER BY ?s ?p ?o"""
        result = {"sparql": query, "executed": execute, "limit": limit, "offset": offset}
        if execute:
            items = shape(self.store.query(query)["results"]["bindings"])
            if plan.get("id") and not items:
                raise HTTPException(404, "Ressource introuvable dans cette collection.")
            result.update(data=items, total=self.total(body))
        return result

    def count(self, plan, execute=True):
        body = where(plan["collection"], plan.get("types"), None, plan.get("search"),
                     plan.get("issue"), plan.get("filters", []))
        query = PREFIXES + f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ {body} }}"
        result = {"sparql": query, "executed": execute}
        if execute:
            result["count"] = self.total(body)
        return result

    def types_of(self, collection, identifier):
        subject = iri(identifier)
        rows = self.store.query(PREFIXES + f"SELECT DISTINCT ?type WHERE {{ {scope(collection, subject=subject)} "
                                f"{subject} rdf:type ?type . }}")["results"]["bindings"]
        types = [local(r["type"]["value"]) for r in rows if r["type"]["value"].startswith(NAMESPACE)]
        if not types:
            raise HTTPException(404, "Ressource introuvable dans cette collection.")
        return types

    def triples(self, subject, types, properties):
        triples = []
        for name, values in properties.items():
            spec = SCHEMA["properties"].get(name)
            if not spec or not any(set(spec["domains"]).issubset(ancestors(t)) for t in types):
                raise HTTPException(422, f"Propriété {name} incompatible avec la classe {', '.join(types)}.")
            for value in values if isinstance(values, list) else [values]:
                if value is None:
                    raise HTTPException(422, "Utilisez [] pour retirer les valeurs d'une propriété.")
                obj = term(name, value)
                if spec["kind"] == "ObjectProperty":
                    for target in spec["ranges"]:
                        if not self.store.query(PREFIXES + f"ASK {{ {obj} rdf:type/rdfs:subClassOf* eg:{target} }}")["boolean"]:
                            raise HTTPException(422, f"La cible de {name} doit exister et être de type {target}.")
                triples.append(f"{subject} eg:{name} {obj} .")
        return triples

    def write(self, plan, execute=True):
        action, collection, identifier = plan["action"], plan["collection"], plan.get("id")
        if not identifier:
            raise HTTPException(422, "Un identifiant explicite est obligatoire pour une écriture.")
        subject = iri(identifier)
        properties, label = plan.get("properties") or {}, plan.get("label")
        if action == "create":
            types = [check_type(collection, plan.get("type") or COLLECTIONS[collection])]
            if self.store.query(f"ASK {{ {{ {subject} ?p ?o }} UNION {{ ?s ?p {subject} }} }}")["boolean"]:
                raise HTTPException(409, "Cet identifiant existe déjà.")
        elif action in ("update", "delete"):
            types = self.types_of(collection, identifier)
        else:
            raise HTTPException(422, "Action inconnue.")
        triples = self.triples(subject, types, properties)
        if label is not None:
            triples.append(f"{subject} rdfs:label {Literal(label).n3()} .")
        if action == "create":
            head = f"{subject} rdf:type eg:{types[0]} , {NAMED_INDIVIDUAL} ."
            query = PREFIXES + "INSERT DATA { " + " ".join([head] + triples) + " }"
        elif action == "update":
            predicates = ["eg:" + p for p in properties] + (["rdfs:label"] if label is not None else [])
            if not predicates:
                raise HTTPException(422, "Aucun champ à modifier.")
            query = PREFIXES + f"""DELETE {{ {subject} ?p ?old }}
              INSERT {{ {' '.join(triples)} }}
              WHERE {{ VALUES ?p {{ {' '.join(predicates)} }} OPTIONAL {{ {subject} ?p ?old }} }}"""
        else:
            # Retire aussi les liens entrants pour ne laisser aucune référence orpheline.
            query = PREFIXES + f"""DELETE {{ {subject} ?p ?o . ?source ?relation {subject} . }}
              WHERE {{ {{ {subject} ?p ?o }} UNION {{ ?source ?relation {subject} }} }}"""
        if execute:
            self.store.request(query, update=True)
        return {"id": identifier, "sparql": query, "executed": execute}

    # -- Lectures spécialisées -------------------------------------------------------------------
    def relations(self, collection, identifier):
        """Ressources liées (dans les deux sens), avec leur libellé et leur table d'origine."""
        subject = iri(identifier)
        self.types_of(collection, identifier)
        rows = self.store.query(PREFIXES + f"""SELECT ?other ?p ?dir ?lbl ?nom ?type WHERE {{
          {{ VALUES ?dir {{ "out" }} {subject} ?p ?other }} UNION {{ VALUES ?dir {{ "in" }} ?other ?p {subject} }}
          FILTER(isIRI(?other) && ?other != {subject} && STRSTARTS(STR(?other), "{NAMESPACE}") && STRSTARTS(STR(?p), "{NAMESPACE}"))
          OPTIONAL {{ ?other rdfs:label ?lbl }} OPTIONAL {{ ?other eg:nomComplet ?nom }}
          OPTIONAL {{ ?other rdf:type ?type . FILTER(STRSTARTS(STR(?type), "{NAMESPACE}")) }}
        }}""")["results"]["bindings"]
        nodes = {}
        for row in rows:
            uri = row["other"]["value"]
            node = nodes.setdefault(uri, {"id": local(uri), "name": local(uri), "types": set(), "links": set()})
            node["name"] = row.get("nom", row.get("lbl", {"value": node["name"]}))["value"]
            if "type" in row:
                node["types"].add(local(row["type"]["value"]))
            node["links"].add((local(row["p"]["value"]), row["dir"]["value"]))
        result = []
        for node in sorted(nodes.values(), key=lambda n: n["name"].lower())[:300]:
            kind = most_specific(list(node["types"]))
            owner = next((c for c, root in COLLECTIONS.items() if kind and root in ancestors(kind)), None)
            result.append({"id": node["id"], "name": node["name"], "type": kind, "collection": owner,
                           "links": [{"property": p, "direction": d} for p, d in sorted(node["links"])]})
        return {"id": identifier, "nodes": result}

    def lookup(self, cls, q="", limit=30):
        """Liste courte {id, name} d'instances d'une classe, pour alimenter les listes de relations."""
        if cls not in SCHEMA["classes"]:
            raise HTTPException(422, f"Classe inconnue : {cls}")
        terms = q.lower().split()
        text = (f'LCASE(CONCAT(STRAFTER(STR(?s), "{NAMESPACE}"), " ", COALESCE(STR(?lbl), ""), " ", '
                'COALESCE(STR(?nom), ""), " ", COALESCE(STR(?ident), "")))')
        flt = " FILTER(" + " && ".join(f"CONTAINS({text}, {literal(t)})" for t in terms) + ")" if terms else ""
        rows = self.store.query(PREFIXES + f"""SELECT DISTINCT ?s ?lbl ?nom WHERE {{
          VALUES ?root {{ eg:{cls} }} ?s rdf:type/rdfs:subClassOf* ?root . {NAMES}{flt}
        }} ORDER BY ?s LIMIT {min(max(limit, 1), 200) * 3}""")["results"]["bindings"]
        found = {}
        for row in rows:
            name = row.get("nom", row.get("lbl", {"value": local(row["s"]["value"])}))["value"]
            found.setdefault(local(row["s"]["value"]), name)
        return [{"id": i, "name": n} for i, n in list(found.items())[:limit]]

    def stats(self):
        totals, by_type = {}, {}
        for collection in COLLECTIONS:
            totals[collection] = self.total(scope(collection))
            rows = self.store.query(PREFIXES + f"""SELECT ?type (COUNT(DISTINCT ?s) AS ?n) WHERE {{
              {scope(collection)} ?s rdf:type ?type . FILTER(STRSTARTS(STR(?type), "{NAMESPACE}"))
            }} GROUP BY ?type ORDER BY DESC(?n) ?type""")["results"]["bindings"]
            by_type[collection] = [{"type": local(r["type"]["value"]), "count": int(r["n"]["value"])} for r in rows]
        quality = [{"key": key, "collection": collection, "title": title,
                    "count": self.total(f"{scope(collection)} {clause}")}
                   for key, (collection, title, clause) in ISSUES.items()]
        rows = self.store.query(PREFIXES + """SELECT ?o ?name (COUNT(DISTINCT ?p) AS ?n) WHERE {
          { ?p eg:travaillePour ?o } UNION { ?o eg:emploiePersonne ?p }
          OPTIONAL { ?o rdfs:label ?name }
        } GROUP BY ?o ?name ORDER BY DESC(?n) LIMIT 5""")["results"]["bindings"]
        top = [{"id": local(r["o"]["value"]), "name": r.get("name", {"value": local(r["o"]["value"])})["value"],
                "employees": int(r["n"]["value"])} for r in rows]
        return {"totals": totals, "by_type": by_type, "quality": quality, "top_organisations": top}
