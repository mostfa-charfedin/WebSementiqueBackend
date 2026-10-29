"""Tests du module Gestion des acteurs et des organisations : HTTP -> NLP -> SPARQL sur un graphe isolé."""
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from rdflib import Graph, Namespace, RDF, RDFS, Literal

import main
import repository as repo

EG = Namespace(repo.NAMESPACE)


class ActeursTests(unittest.TestCase):
    def setUp(self):
        self.graph = Graph()
        for child, parents in repo.SCHEMA["classes"].items():
            for parent in parents:
                self.graph.add((EG[child], RDFS.subClassOf, EG[parent]))
        org = EG.service_distribution_ariana
        self.graph.add((org, RDF.type, EG.ServiceDistributionUrbain))
        self.graph.add((org, RDFS.label, Literal("service distribution ariana")))
        self.graph.add((org, EG.emploiePersonne, EG.technicien_yassine))
        self.graph.add((EG.centre_vide, RDF.type, EG.CentreConduiteTransport))
        self.graph.add((EG.centre_vide, RDFS.label, Literal("centre vide")))
        yassine = EG.technicien_yassine
        self.graph.add((yassine, RDF.type, EG.TechnicienCompteurs))
        self.graph.add((yassine, RDFS.label, Literal("technicien yassine trabelsi 731862")))
        self.graph.add((yassine, EG.nomComplet, Literal("Yassine Trabelsi")))
        self.graph.add((yassine, EG.travaillePour, org))
        self.graph.add((EG.salma, RDF.type, EG.ResponsableSecteurUrbain))
        self.graph.add((EG.salma, RDFS.label, Literal("responsable salma mansour")))
        self.graph.add((EG.salma, EG.nomComplet, Literal("Salma Mansour")))
        self.graph.add((EG.anonyme, RDF.type, EG.OccupantMaisonIndividuelle))
        self.graph.add((EG.anonyme, RDFS.label, Literal("occupant anonyme")))
        self.updates = []
        mock = patch.object(repo.httpx, "post", side_effect=self.fuseki)
        mock.start()
        self.addCleanup(mock.stop)
        self.client = TestClient(main.app)

    def fuseki(self, url, *, content, **kwargs):
        query = content.decode("utf-8")
        request = httpx.Request("POST", url)
        if url == main.FUSEKI_UPDATE_ENDPOINT:
            self.updates.append(query)
            self.graph.update(query)
            return httpx.Response(204, request=request)
        return httpx.Response(200, json=json.loads(self.graph.query(query).serialize(format="json")), request=request)

    def nlp(self, prompt, execute=True):
        return self.client.post("/api/acteurs/nlp", json={"prompt": prompt, "execute": execute})

    def ids(self, response):
        return sorted(item["id"] for item in response.json()["data"])

    def test_list_filters_search_and_pagination(self):
        r = self.client.get("/api/acteurs/personnes")
        self.assertEqual(r.json()["total"], 3)
        self.assertEqual(self.ids(self.client.get("/api/acteurs/personnes?type=Technicien")), ["technicien_yassine"])
        self.assertEqual(self.ids(self.client.get("/api/acteurs/personnes?search=salma mansour")), ["salma"])
        self.assertEqual(self.ids(self.client.get("/api/acteurs/personnes?issue=sans_organisation")), ["anonyme", "salma"])
        self.assertEqual(self.ids(self.client.get("/api/acteurs/personnes?filter=travaillePour:service distribution")),
                         ["technicien_yassine"])
        self.assertEqual(len(self.client.get("/api/acteurs/personnes?limit=1").json()["data"]), 1)
        self.assertEqual(self.client.get("/api/acteurs/personnes?issue=sans_employe").status_code, 422)
        self.assertEqual(self.client.get("/api/acteurs/organisations/salma").status_code, 404)

    def test_item_shape(self):
        item = self.client.get("/api/acteurs/personnes/technicien_yassine").json()["data"][0]
        self.assertEqual((item["type"], item["name"]), ("TechnicienCompteurs", "Yassine Trabelsi"))
        self.assertEqual(item["properties"]["travaillePour"], ["service_distribution_ariana"])

    def test_crud_rest_with_relations(self):
        body = {"id": "tech_demo", "type": "Technicien", "label": "Technicien démo",
                "properties": {"nomComplet": "Demo Test", "travaillePour": ["service_distribution_ariana"]}}
        self.assertEqual(self.client.post("/api/acteurs/personnes", json=body).status_code, 201)
        self.assertEqual(self.client.post("/api/acteurs/personnes", json=body).status_code, 409)
        patch_body = {"properties": {"nomComplet": "Nouveau Nom", "travaillePour": []}}
        self.assertEqual(self.client.patch("/api/acteurs/personnes/tech_demo", json=patch_body).status_code, 200)
        item = self.client.get("/api/acteurs/personnes/tech_demo").json()["data"][0]
        self.assertEqual(item["properties"], {"nomComplet": ["Nouveau Nom"]})
        self.assertEqual(self.client.delete("/api/acteurs/personnes/tech_demo").status_code, 200)
        self.assertEqual(self.client.get("/api/acteurs/personnes/tech_demo").status_code, 404)

    def test_validation(self):
        post = lambda collection, body: self.client.post(f"/api/acteurs/{collection}", json=body)
        self.assertEqual(post("personnes", {"id": "x", "type": "Reseau"}).status_code, 422)
        self.assertEqual(post("personnes", {"id": "x", "properties": {"tensionV": 1}}).status_code, 422)
        self.assertEqual(post("personnes", {"id": "x", "properties": {"travaillePour": ["salma"]}}).status_code, 422)
        self.assertEqual(post("personnes", {"id": "x y"}).status_code, 422)
        self.assertEqual(self.client.patch("/api/acteurs/personnes/salma", json={"id": "z"}).status_code, 422)

    def test_delete_removes_incoming_links(self):
        self.client.delete("/api/acteurs/personnes/technicien_yassine")
        self.assertNotIn((EG.service_distribution_ariana, EG.emploiePersonne, EG.technicien_yassine), self.graph)

    def test_relations_both_directions(self):
        nodes = self.client.get("/api/acteurs/organisations/service_distribution_ariana/relations").json()["nodes"]
        self.assertEqual(nodes[0]["id"], "technicien_yassine")
        self.assertEqual(nodes[0]["collection"], "personnes")
        self.assertEqual({(l["property"], l["direction"]) for l in nodes[0]["links"]},
                         {("emploiePersonne", "out"), ("travaillePour", "in")})

    def test_stats_lookup_schema(self):
        stats = self.client.get("/api/acteurs/stats").json()
        self.assertEqual(stats["totals"], {"personnes": 3, "organisations": 2})
        quality = {q["key"]: q["count"] for q in stats["quality"]}
        self.assertEqual((quality["sans_nom"], quality["sans_organisation"], quality["sans_employe"]), (1, 2, 1))
        self.assertEqual(stats["top_organisations"][0]["employees"], 1)
        self.assertEqual(self.client.get("/api/acteurs/lookup?cls=Organisation&q=ariana").json()[0]["id"],
                         "service_distribution_ariana")
        schema = self.client.get("/api/acteurs/schema").json()
        self.assertIn("travaillePour", schema["collections"]["personnes"]["classes"][0]["properties"])
        self.assertEqual(schema["properties"]["travaillePour"]["targets"], ["Organisation"])

    def test_nlp_reads(self):
        cases = {
            "Affiche les personnes": ["anonyme", "salma", "technicien_yassine"],
            "Liste les techniciens": ["technicien_yassine"],
            "Affiche les responsables": ["salma"],
            "Quels techniciens travaillent pour service_distribution_ariana ?": ["technicien_yassine"],
            "Qui travaille pour le service distribution ariana": ["technicien_yassine"],
            "Affiche les personnes nommées Salma": ["salma"],
            "personnes sans organisation": ["anonyme", "salma"],
            "Liste les personnes sans nom": ["anonyme"],
            'Cherche les personnes "yassine trabelsi"': ["technicien_yassine"],
            "Affiche les personnes nomComplet=\"Salma Mansour\"": ["salma"],
        }
        for prompt, expected in cases.items():
            r = self.nlp(prompt)
            self.assertEqual(r.status_code, 200, f"{prompt}: {r.text}")
            self.assertEqual(self.ids(r), expected, prompt)
        r = self.nlp("Liste les organisations qui emploient yassine")
        self.assertEqual(self.ids(r), ["service_distribution_ariana"])
        self.assertEqual(self.ids(self.nlp("Affiche les centres")), ["centre_vide"])
        self.assertEqual(self.ids(self.nlp("organisations sans employé")), ["centre_vide"])

    def test_nlp_count_and_preview(self):
        r = self.nlp("Combien de personnes sans organisation ?")
        self.assertEqual(r.json()["count"], 2)
        r = self.nlp("Combien de techniciens", execute=False)
        self.assertFalse(r.json()["executed"])
        self.assertNotIn("count", r.json())
        self.assertIn("explain", r.json())

    def test_nlp_writes(self):
        r = self.nlp('Crée un technicien nomComplet="Ali Ben" travaillePour=service_distribution_ariana')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["id"], "ali_ben")
        self.assertIn((EG.ali_ben, EG.travaillePour, EG.service_distribution_ariana), self.graph)
        r = self.nlp("Modifie la personne id=ali_ben etatService=\"en congé\"")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([str(o) for o in self.graph.objects(EG.ali_ben, EG.etatService)], ["en congé"])
        updates = len(self.updates)
        self.assertFalse(self.nlp("Supprime la personne id=ali_ben", execute=False).json()["executed"])
        self.assertEqual(len(self.updates), updates)
        self.assertEqual(self.nlp("Supprime la personne id=ali_ben").status_code, 200)
        self.assertNotIn((EG.ali_ben, RDF.type, EG.Technicien), self.graph)
        self.assertEqual(self.nlp('Ajoute une organisation "Nouveau Service"').json()["id"], "nouveau_service")

    def test_nlp_rejections(self):
        for prompt in ["Bonjour", "Affiche tout", "Affiche les personnes et les organisations",
                       "Supprime les personnes", "Supprime la personne", "Affiche les personnes zorglub",
                       "Modifie la personne id=salma", "Supprime et crée la personne id=a", "Affiche les personnes foo=1"]:
            self.assertEqual(self.nlp(prompt).status_code, 422, prompt)

    def test_reseaux_module_still_works(self):
        self.assertEqual(self.client.get("/api/reseaux").status_code, 200)
        self.assertEqual(self.client.get("/api/schema").status_code, 200)


if __name__ == "__main__":
    unittest.main()
