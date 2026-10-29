"""Tests sur un graphe isolé : aucune écriture dans le dataset Fuseki réel."""
import unittest
from pathlib import Path

from rdflib import Graph, RDF, RDFS, OWL

import repository as repo
import test_backend
from test_backend import EG

BASE = "/api/gestion-informations-equipements"


class InformationsEquipementsTests(unittest.TestCase):
    setUp = test_backend.BackendTests.setUp
    fuseki = test_backend.BackendTests.fuseki

    def test_crud_rest_both_collections(self):
        for collection, kind, properties in [
            ("equipements", "CapteurTemperature", {"temperatureC": 24.5}),
            ("informations", "MesureElectrique", {"decritEquipement": "demo_equipements"}),
        ]:
            url = f"{BASE}/{collection}"
            body = {"id": f"demo_{collection}", "type": kind, "properties": properties}
            r = self.client.post(url, json=body)
            self.assertEqual(r.status_code, 201, r.text)
            self.assertEqual(self.client.post(url, json=body).status_code, 409)
            self.assertEqual(len(self.client.get(url).json()["data"]), 1)
            detail = f"{url}/demo_{collection}"
            self.assertEqual(self.client.get(detail).status_code, 200)
            self.assertEqual(self.client.patch(detail, json={"label": "Modifié"}).status_code, 200)
        self.assertEqual(self.client.delete(f"{BASE}/equipements/demo_equipements").status_code, 200)
        self.assertFalse(list(self.graph.triples((None, EG.decritEquipement, EG.demo_equipements))))
        self.assertEqual(self.client.delete(f"{BASE}/informations/demo_informations").status_code, 200)
        self.assertEqual(self.client.get(f"{BASE}/informations/demo_informations").status_code, 404)

    def test_nlp_crud_and_subclasses(self):
        for noun, kind, prop in [("capteur", "CapteurTemperature", "temperatureC=25"),
                                  ("information", "MesureElectrique", "")]:
            for prompt in [f"Crée un {noun} id=demo type={kind} {prop}",
                           f"Affiche les {noun}s id=demo",
                           f'Modifie le {noun} id=demo label="Nouveau"',
                           f"Supprime le {noun} id=demo"]:
                r = self.client.post(f"{BASE}/nlp", json={"prompt": prompt})
                self.assertEqual(r.status_code, 200, r.text)
        for prompt in ["Liste les équipements", "Affiche les informations", "Liste les compteurs intelligents"]:
            r = self.client.post(f"{BASE}/nlp", json={"prompt": prompt, "execute": False})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertFalse(r.json()["executed"])

    def test_invalid_requests_do_not_write(self):
        for prompt in ["Ne supprime pas le capteur id=demo", "Supprime tous les équipements",
                       "Liste les réseaux", "Affiche les équipements et supprime les informations"]:
            self.assertEqual(self.client.post(f"{BASE}/nlp", json={"prompt": prompt}).status_code, 422)
        for kind, props in [("Reseau", {}), ("Capteur", {"temperatureC": 20}),
                            ("CapteurTemperature", {"temperatureC": "abc"}),
                            ("Mesure", {"decritEquipement": "inexistant"})]:
            collection = "informations" if kind == "Mesure" else "equipements"
            r = self.client.post(f"{BASE}/{collection}", json={"id": "demo", "type": kind, "properties": props})
            self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(self.updates, [])

    def test_schema_matches_supplied_rdf(self):
        graph = Graph().parse(Path(__file__).resolve().parent.parent / "EnergieSmartGridWEB.rdf")
        schema = self.client.get(f"{BASE}/schema").json()
        for classes in schema["collections"].values():
            for kind, properties in classes.items():
                self.assertIn((EG[kind], RDF.type, OWL.Class), graph)
                for name, spec in properties.items():
                    self.assertEqual({str(v).rsplit("#", 1)[-1] for v in graph.objects(EG[name], RDFS.domain)}, set(spec["domains"]))
                    self.assertEqual({str(v).rsplit("#", 1)[-1] for v in graph.objects(EG[name], RDFS.range)}, set(spec["ranges"]))


if __name__ == "__main__":
    unittest.main()
