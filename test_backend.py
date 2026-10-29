"""Tests du parcours HTTP → NLP → SPARQL sur un graphe RDF isolé."""
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from rdflib import Graph, Namespace, RDF, RDFS, Literal

import main
import nlp
import repository as repo

EG = Namespace(repo.NAMESPACE)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.graph = Graph()
        for child, parents in repo.SCHEMA["classes"].items():
            for parent in parents:
                self.graph.add((EG[child], RDFS.subClassOf, EG[parent]))
        self.graph.add((EG.reseau_test, RDF.type, EG.ReseauDistributionUrbain))
        self.graph.add((EG.reseau_test, RDFS.label, Literal("Réseau Tunis", lang="fr")))
        self.graph.add((EG.reseau_test, EG.tensionNominaleV, Literal(30000)))
        self.graph.add((EG.ligne_test, RDF.type, EG.DepartResidentiel230V))
        self.graph.add((EG.ligne_test, EG.appartientAuReseau, EG.reseau_test))
        self.updates = []
        self.mock = patch.object(repo.httpx, "post", side_effect=self.fuseki)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.client = TestClient(main.app)

    def fuseki(self, url, *, content, **kwargs):
        query = content.decode("utf-8")
        request = httpx.Request("POST", url)
        if url == main.FUSEKI_UPDATE_ENDPOINT:
            self.updates.append(query)
            self.graph.update(query)
            return httpx.Response(204, request=request)
        result = json.loads(self.graph.query(query).serialize(format="json"))
        return httpx.Response(200, json=result, request=request)

    def test_reads_include_subclasses_and_full_multivalued_resources(self):
        response = self.client.get("/api/reseaux?limit=1")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"][0]["id"], "reseau_test")
        self.assertIn("tensionNominaleV", response.json()["data"][0]["properties"])
        self.assertEqual(self.client.get("/api/infrastructures/reseau_test").status_code, 404)

    def test_nlp_read_filters_and_preview(self):
        for text in ["Affiche les réseaux à Tunis", "Liste les réseaux tensionNominaleV>=30000",
                     "Affiche les réseaux dont la tension nominale est supérieure à 20000 V"]:
            r = self.client.post("/api/nlp", json={"prompt": text})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(len(r.json()["data"]), 1)
        r = self.client.post("/api/nlp", json={"prompt": "Liste les transformateurs", "execute": False})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["executed"])

    def test_crud_for_both_collections_through_nlp(self):
        for table, noun, kind, prop, value in [
            ("reseaux", "réseau", "ReseauDistribution", "tensionNominaleV", 30000),
            ("infrastructures", "transformateur", "Transformateur30kV400V", "tensionEntreeV", 30000),
        ]:
            text = f'Crée un {noun} id=nouveau type={kind} label="Exemple" {prop}={value}'
            r = self.client.post("/api/nlp", json={"prompt": text})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(self.client.get(f"/api/{table}/nouveau").status_code, 200)
            r = self.client.post("/api/nlp", json={"prompt": f'Modifie le {noun} id=nouveau etatService="hors service"'})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(str(self.graph.value(EG.nouveau, EG.etatService)), "hors service")
            r = self.client.post("/api/nlp", json={"prompt": f'Supprime le {noun} id=nouveau'})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(self.client.get(f"/api/{table}/nouveau").status_code, 404)

    def test_rest_crud_relations_and_clear(self):
        r = self.client.post("/api/infrastructures", json={"id": "nouvelle_ligne", "type": "LigneElectrique",
                "properties": {"appartientAuReseau": ["reseau_test"], "longueurKm": 2.5}})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(self.client.post("/api/infrastructures", json={"id": "nouvelle_ligne", "type": "LigneElectrique"}).status_code, 409)
        self.assertEqual(self.client.patch("/api/infrastructures/nouvelle_ligne", json={"properties": {"longueurKm": []}}).status_code, 200)
        self.assertIsNone(self.graph.value(EG.nouvelle_ligne, EG.longueurKm))
        self.assertEqual(self.client.delete("/api/reseaux/reseau_test").status_code, 200)
        self.assertFalse(list(self.graph.triples((None, None, EG.reseau_test))))
        self.assertTrue(list(self.graph.triples((EG.ligne_test, None, None))))

    def test_invalid_inputs_do_not_write(self):
        for text in ["Supprime tous les réseaux", "Ne supprime pas le réseau id=reseau_test",
                     "Affiche les réseaux sauf Tunis", "Affiche les réseaux et supprime les lignes",
                     "Affiche les réseaux puissanceInconnue=20", "Modifie le réseau id=reseau_test",
                     'Supprime le réseau id=reseau_test etatService="en service"']:
            r = self.client.post("/api/nlp", json={"prompt": text})
            self.assertEqual(r.status_code, 422, text + r.text)
        for properties in [{"tensionNominaleV": "oops"}, {"tensionV": 10},
                           {"estGerePar": "reseau_test"}, {"inconnue": 2}]:
            r = self.client.patch("/api/reseaux/reseau_test", json={"properties": properties})
            self.assertEqual(r.status_code, 422, r.text)
        self.assertFalse(self.updates)

    def test_preview_write_does_not_mutate(self):
        r = self.client.post("/api/nlp", json={"prompt": "Supprime le réseau id=reseau_test", "execute": False})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["executed"])
        self.assertFalse(self.updates)

    def test_literal_injection_is_data(self):
        r = self.client.patch("/api/reseaux/reseau_test", json={"label": '" } ; DROP ALL ; #\ntexte'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(list(self.graph.triples((EG.ligne_test, None, None))))

    def test_fuseki_errors_are_http_errors(self):
        with patch.object(repo.httpx, "post", side_effect=httpx.ConnectError("offline")):
            self.assertEqual(self.client.get("/api/health").status_code, 502)
        with patch.object(repo.httpx, "post", side_effect=httpx.ReadTimeout("timeout")):
            self.assertEqual(self.client.get("/api/health").status_code, 504)


if __name__ == "__main__":
    unittest.main()
