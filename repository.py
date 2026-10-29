"""Validation RDF, construction SPARQL et accès HTTP à Fuseki."""
import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from fastapi import HTTPException
from rdflib import Literal, URIRef, XSD

SCHEMA = json.loads(Path(__file__).with_name("ontology_schema.json").read_text(encoding="utf-8"))
NAMESPACE = SCHEMA["namespace"]
ROOTS = {
    "installations": ["Installation"],
    "reserves": ["Reserve"],
    "reseaux": ["Reseau"],
    "infrastructures": ["Ouvrage", "PosteCommande"],
    "lieux": ["Lieu"],
    "transports": ["Transport"],
}
PREFIXES = f"""PREFIX eg: <{NAMESPACE}>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""


def ancestors(name):
    found, pending = {name}, [name]
    while pending:
        for parent in SCHEMA["classes"].get(pending.pop(), []):
            if parent not in found:
                found.add(parent)
                pending.append(parent)
    return found


def valid_type(collection, name):
    if collection not in ROOTS or name not in SCHEMA["classes"] or not ancestors(name).intersection(ROOTS[collection]):
        raise HTTPException(422, f"Classe incompatible avec {collection} : {name}")
    return name


def iri(identifier):
    if not isinstance(identifier, str):
        raise HTTPException(422, "Une relation attend un identifiant RDF.")
    local = identifier.removeprefix(NAMESPACE).removeprefix("eg:")
    if not re.fullmatch(r"[\w][\w.-]*", local, re.UNICODE):
        raise HTTPException(422, "Identifiant RDF invalide (nom local ou URI de cette ontologie attendu).")
    return URIRef(NAMESPACE + local).n3()


def literal(value):
    return Literal(value).n3()


def term(name, value):
    prop = SCHEMA["properties"][name]
    if prop["kind"] == "ObjectProperty":
        return iri(value)
    datatype = prop["ranges"][0]
    try:
        if datatype == "decimal":
            if isinstance(value, bool):
                raise ValueError()
            number = Decimal(str(value))
            if not number.is_finite():
                raise ValueError()
            return Literal(format(number, "f"), datatype=XSD.decimal).n3()
        if datatype == "integer":
            if isinstance(value, bool) or not re.fullmatch(r"[+-]?\d+", str(value)):
                raise ValueError()
            return Literal(int(value), datatype=XSD.integer).n3()
        if datatype == "dateTime":
            if not isinstance(value, str) or "T" not in value:
                raise ValueError()
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        if datatype == "string" and not isinstance(value, str):
            raise ValueError()
        if datatype == "boolean" and not isinstance(value, bool):
            raise ValueError()
        return Literal(value, datatype=URIRef(str(XSD) + datatype)).n3()
    except (ValueError, TypeError, InvalidOperation):
        raise HTTPException(422, f"{name} attend une valeur de type {datatype}.") from None


def scope(collection, subject="?s", class_name=None):
    roots = [valid_type(collection, class_name)] if class_name else ROOTS[collection]
    return "VALUES ?root { " + " ".join("eg:" + r for r in roots) + " } " + f"{subject} rdf:type/rdfs:subClassOf* ?root ."


def read_query(plan):
    subject = iri(plan["id"]) if plan.get("id") else "?s"
    conditions = scope(plan["collection"], class_name=plan.get("type"))
    if subject != "?s":
        conditions += f" VALUES ?s {{ {subject} }}"
    if plan.get("search"):
        conditions += f" ?s rdfs:label ?label . FILTER(CONTAINS(LCASE(STR(?label)), LCASE({literal(plan['search'])})))"
    for index, f in enumerate(plan.get("filters", [])):
        name, op, value = f["property"], f["operator"], f["value"]
        if name not in SCHEMA["properties"] or op not in ["=", ">", "<", ">=", "<="]:
            raise HTTPException(422, "Filtre non reconnu.")
        conditions += f" ?s eg:{name} ?f{index} . FILTER(?f{index} {op} {term(name, value)})"
    return PREFIXES + f"""SELECT ?s ?p ?o WHERE {{
      {{ SELECT DISTINCT ?s WHERE {{ {conditions} }} ORDER BY ?s LIMIT {int(plan.get('limit', 50))} OFFSET {int(plan.get('offset', 0))} }}
      ?s ?p ?o .
    }} ORDER BY ?s ?p ?o"""


def public_schema():
    result = {}
    for collection in ROOTS:
        classes = [c for c in SCHEMA["classes"] if ancestors(c).intersection(ROOTS[collection])]
        result[collection] = {c: {p: spec for p, spec in SCHEMA["properties"].items()
                                  if set(spec["domains"]).issubset(ancestors(c))} for c in classes}
    return {"namespace": NAMESPACE, "collections": result}


class Store:
    def __init__(self, query_url, update_url, username="", password="", timeout=15):
        self.query_url, self.update_url = query_url, update_url
        self.auth = (username, password) if username else None
        self.timeout = timeout

    def request(self, query, update=False):
        try:
            response = httpx.post(
                self.update_url if update else self.query_url,
                content=query.encode("utf-8"), auth=self.auth, timeout=self.timeout,
                headers={"Content-Type": "application/sparql-update" if update else "application/sparql-query",
                         "Accept": "application/sparql-results+json"},
            )
            response.raise_for_status()
            return None if update else response.json()
        except httpx.TimeoutException:
            raise HTTPException(504, "Fuseki ne répond pas dans le délai configuré.") from None
        except (httpx.HTTPError, ValueError):
            logging.exception("Échec de la communication avec Fuseki")
            raise HTTPException(502, "Connexion Fuseki impossible ou requête refusée. Vérifiez les endpoints et les droits.") from None

    def query(self, query):
        return self.request(query)

    def types(self, collection, identifier):
        rows = self.query(PREFIXES + f"SELECT DISTINCT ?type WHERE {{ {scope(collection, iri(identifier))} {iri(identifier)} rdf:type ?type . }}")["results"]["bindings"]
        types = [r["type"]["value"].removeprefix(NAMESPACE) for r in rows
                 if r["type"]["value"].startswith(NAMESPACE)]
        if not types:
            raise HTTPException(404, "Ressource introuvable dans cette collection.")
        return types

    def run(self, plan, execute=True):
        action, collection = plan["action"], plan["collection"]
        if action == "read":
            query = read_query(plan)
            result = {"action": action, "collection": collection, "sparql": query, "executed": execute}
            if execute:
                rows = self.query(query)["results"]["bindings"]
                resources = {}
                for row in rows:
                    uri = row["s"]["value"]
                    item = resources.setdefault(uri, {"id": uri.removeprefix(NAMESPACE), "uri": uri, "properties": {}})
                    prop = row["p"]["value"].removeprefix(NAMESPACE)
                    item["properties"].setdefault(prop, []).append(row["o"])
                if plan.get("id") and not resources:
                    raise HTTPException(404, "Ressource introuvable dans cette collection.")
                result["data"] = list(resources.values())
            return result

        identifier = plan.get("id")
        if not identifier:
            raise HTTPException(422, "Un identifiant explicite est obligatoire pour une écriture.")
        subject = iri(identifier)
        properties = plan.get("properties") or {}
        if action == "create":
            class_name = valid_type(collection, plan.get("type"))
            if self.query(f"ASK {{ {{ {subject} ?p ?o }} UNION {{ ?s ?p {subject} }} }}")["boolean"]:
                raise HTTPException(409, "Cet identifiant RDF existe déjà.")
            types = [class_name]
        else:
            types = self.types(collection, identifier)
            if plan.get("type") and not any(plan["type"] in ancestors(t) for t in types):
                raise HTTPException(422, "La classe demandée ne correspond pas à la ressource.")

        triples = []
        for name, values in properties.items():
            matching = [t for t in types if name in SCHEMA["properties"] and
                        set(SCHEMA["properties"][name]["domains"]).issubset(ancestors(t))]
            if not matching:
                raise HTTPException(422, f"Propriété {name} incompatible avec les classes {types}.")
            prop = SCHEMA["properties"][name]
            for value in values if isinstance(values, list) else [values]:
                if value is None:
                    raise HTTPException(422, "Utilisez [] pour retirer les valeurs d'une propriété.")
                obj = term(name, value)
                if prop["kind"] == "ObjectProperty":
                    for target in prop["ranges"]:
                        if not self.query(PREFIXES + f"ASK {{ {obj} rdf:type/rdfs:subClassOf* eg:{target} }}")["boolean"]:
                            raise HTTPException(422, f"La cible de {name} doit exister et être de type {target}.")
                triples.append(f"{subject} eg:{name} {obj} .")
        if plan.get("label") is not None:
            triples.append(f"{subject} rdfs:label {Literal(plan['label'], lang='fr').n3()} .")
        if action == "create":
            triples.insert(0, f"{subject} rdf:type eg:{types[0]} .")
            query = PREFIXES + "INSERT DATA { " + " ".join(triples) + " }"
        elif action == "update":
            predicates = ["eg:" + p for p in properties]
            if plan.get("label") is not None:
                predicates.append("rdfs:label")
            if not predicates:
                raise HTTPException(422, "Aucun champ à modifier.")
            query = PREFIXES + f"""DELETE {{ {subject} ?p ?old }}
              INSERT {{ {' '.join(triples)} }}
              WHERE {{ VALUES ?p {{ {' '.join(predicates)} }} OPTIONAL {{ {subject} ?p ?old }} }}"""
        elif action == "delete":
            # Retirer aussi les relations entrantes pour éviter les liens pendants.
            query = PREFIXES + f"""DELETE {{ {subject} ?p ?o . ?source ?relation {subject} . }}
              WHERE {{ {{ {subject} ?p ?o }} UNION {{ ?source ?relation {subject} }} }}"""
        else:
            raise HTTPException(422, "Action inconnue.")
        if execute:
            self.request(query, update=True)
        return {"action": action, "collection": collection, "id": identifier,
                "sparql": query, "executed": execute}
