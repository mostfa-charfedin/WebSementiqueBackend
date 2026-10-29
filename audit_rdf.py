"""Contrôles RDF/RDFS de base, sans prétendre être un raisonneur OWL complet."""
import argparse
import json
from itertools import combinations

from rdflib import Graph, Literal, OWL, RDF, RDFS, URIRef


def audit(path):
    graph = Graph().parse(path, format="xml")
    namespace = "https://example.org/energie-smart-grid#"
    classes = set(graph.subjects(RDF.type, OWL.Class))
    individuals = set(graph.subjects(RDF.type, OWL.NamedIndividual))
    objects = set(graph.subjects(RDF.type, OWL.ObjectProperty))
    datatypes = set(graph.subjects(RDF.type, OWL.DatatypeProperty))
    declared = classes | individuals | objects | datatypes

    def short(value):
        return str(value).removeprefix(namespace)

    def parents(cls):
        found, pending = {cls}, [cls]
        while pending:
            for parent in graph.objects(pending.pop(), RDFS.subClassOf):
                if isinstance(parent, URIRef) and parent not in found:
                    found.add(parent)
                    pending.append(parent)
        return found

    types = {s: set().union(*(parents(t) for t in graph.objects(s, RDF.type))) for s in individuals}
    # Inférences simples des domaines et portées, puis héritage de classes.
    for s, p, o in graph:
        if s in types:
            for d in graph.objects(p, RDFS.domain):
                if isinstance(d, URIRef):
                    types[s].update(parents(d))
        if o in types:
            for r in graph.objects(p, RDFS.range):
                if isinstance(r, URIRef):
                    types[o].update(parents(r))
    disjoint = set()
    for a, b in graph.subject_objects(OWL.disjointWith):
        disjoint.add(frozenset([a, b]))
    for node in graph.subjects(RDF.type, OWL.AllDisjointClasses):
        for head in graph.objects(node, OWL.members):
            disjoint.update(frozenset(pair) for pair in combinations(list(graph.items(head)), 2))
    conflicts = [{"individual": short(s), "classes": sorted(short(c) for c in pair)}
                 for s, ts in types.items() for pair in disjoint if pair.issubset(ts)]
    return {
        "triples": len(graph), "classes": len(classes), "individuals": len(individuals),
        "object_properties": len(objects), "datatype_properties": len(datatypes),
        "undeclared_terms": sorted({short(t) for triple in graph for t in triple
                                   if isinstance(t, URIRef) and str(t).startswith(namespace) and t not in declared}),
        "invalid_literals": [{"subject": short(s), "property": short(p), "value": str(o)}
                             for s, p, o in graph if isinstance(o, Literal) and o.ill_typed],
        "multiple_domains": [{"property": short(p), "domains": sorted(short(d) for d in graph.objects(p, RDFS.domain))}
                             for p in sorted(objects | datatypes) if len(set(graph.objects(p, RDFS.domain))) > 1],
        "disjoint_conflicts_after_basic_inference": sorted(conflicts, key=lambda c: (c["individual"], c["classes"])),
        "infrastructure_class_exists": URIRef(namespace + "Infrastructure") in classes,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = json.dumps(audit(args.path), indent=2, ensure_ascii=False)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(report + "\n", encoding="utf-8")
    else:
        print(report)
