# Gestion des informations et des équipements

Ajout backend uniquement. Le routeur est enregistré dans `main.py` avant les routes génériques. Les modules du groupe et l'ancienne route `/api/equipements` restent disponibles. Le moteur SPARQL et le pipeline spaCy existants sont réutilisés avec les deux collections supplémentaires.

## Connexion vérifiée

Les variables sont déjà regroupées au début de `main.py` :

| Variable | Valeur par défaut |
| --- | --- |
| `FUSEKI_BASE_URL` | `http://localhost:3030` |
| `FUSEKI_DATASET` | `Smart-Grid` |
| `FUSEKI_ENDPOINT` (environnement `FUSEKI_QUERY_URL`) | `http://localhost:3030/Smart-Grid/sparql` |
| `FUSEKI_UPDATE_ENDPOINT` (environnement `FUSEKI_UPDATE_URL`) | `http://localhost:3030/Smart-Grid/update` |
| `FUSEKI_USERNAME`, `FUSEKI_PASSWORD` | vides |
| `FUSEKI_TIMEOUT` | 15 secondes |
| `RDF_NAMESPACE` | `https://example.org/energie-smart-grid#` |

Le serveur local expose **`Smart-Grid`**, confirmé par `/$/datasets`. Le chemin `smart-grid` du lien fourni renvoie 404. L'URL avec `/#/dataset/…/query` correspond à l'interface web, pas à l'endpoint HTTP. Les variables peuvent être remplacées dans l'environnement PowerShell ; aucun fichier `.env` n'est chargé.

Le RDF et les déclarations de sous-classes doivent être chargés dans le graphe par défaut du dataset. Le service d'écriture `/update` est déclaré sur le serveur ; les écritures réelles n'ont pas été testées afin de préserver les données du groupe.

## Routes pour le futur frontend

Préfixe : `/api/gestion-informations-equipements`.

Remplacer `{collection}` par `equipements` ou `informations` :

| Méthode | Chemin après le préfixe | Fonction |
| --- | --- | --- |
| GET | `/schema` | Classes et propriétés RDF autorisées |
| POST | `/nlp` | Prompt → spaCy → SPARQL → Fuseki |
| GET | `/{collection}` | Liste, paramètres `type`, `search`, `limit`, `offset` |
| GET | `/{collection}/{id}` | Détail |
| POST | `/{collection}` | Création |
| PATCH | `/{collection}/{id}` | Modification |
| DELETE | `/{collection}/{id}` | Suppression, y compris les relations entrantes |

Exemple envoyé par le frontend à `POST /api/gestion-informations-equipements/nlp` :

```json
{"prompt":"Affiche les capteurs de température", "execute":true}
```

Avec `execute:false`, la réponse expose le SPARQL sans l'exécuter. La validation d'une écriture peut néanmoins effectuer des lectures Fuseki. La réponse contient `action`, `collection`, `sparql`, `executed` et, en lecture exécutée, `data`.

Exemples de prompts acceptés :

```text
Liste les équipements
Affiche les informations
Liste les compteurs intelligents
Affiche les capteurs temperatureC>=25
Crée un capteur type=CapteurTemperature id=capteur_demo temperatureC=24.5
Crée une information type=MesureElectrique id=mesure_demo decritEquipement=capteur_demo
Modifie le capteur id=capteur_demo temperatureC=26
Supprime l'information id=mesure_demo
```

spaCy utilise le tokenizer français et `PhraseMatcher`, sans clé API ni modèle à télécharger. Le vocabulaire est limité aux intentions et classes reconnues ; les phrases ambiguës et les négations sont rejetées avec 422. Les champs d'écriture utilisent les noms RDF exacts sous la forme `propriete=valeur`, avec des guillemets doubles pour les espaces. Un identifiant explicite est requis pour écrire.

Exemple JSON de création d'équipement :

```json
{"id":"capteur_demo","type":"CapteurTemperature","label":"Capteur salle","properties":{"temperatureC":24.5,"uniteMesure":"°C"}}
```

Exemple JSON de création d'information (l'équipement cible doit exister) :

```json
{"id":"mesure_demo","type":"MesureElectrique","properties":{"decritEquipement":"capteur_demo"}}
```

Un PATCH remplace les valeurs des propriétés fournies. `[]` retire une propriété. La classe et l'identifiant sont immuables. Les relations sont vérifiées selon leur portée RDF ; leurs inverses ne sont pas synchronisés automatiquement.

## Vérification RDF

`Equipement` et `Information` existent avec leurs sous-classes. Les noms de classes, domaines et portées exposés par le module sont comparés au fichier `EnergieSmartGridWEB.rdf` dans les tests.

Exemples de propriétés : `temperatureC` pour `CapteurTemperature`, `numeroSerie` pour `CompteurIntelligent`, `puissanceEquipementKW` pour `EquipementElectrique`, `decritEquipement` pour `Information`, `estProduiteParCapteur` pour `Mesure`.

Le fichier ne déclare pas de propriété littérale directement sur `Information` ou `Mesure` ; `label` utilise `rdfs:label`. Aucune propriété de date ou valeur de mesure n'a été inventée pour ces classes.

Le rapport `verification_informations_equipements.json` ne détecte aucun terme local non déclaré ni littéral typé invalide. Point à revoir dans l'ontologie : les deux domaines de `energieProduiteKWh` (`CompteurIntelligent` et `SourceProduction`) imposent une intersection. Le backend refuse donc cette propriété sur un simple compteur. Le RDF original reste intact. Ce contrôle ne constitue pas une validation OWL complète.

## Lancement et tests

Depuis `WebSementiqueBackend` :

```powershell
.\.venv\Scripts\python -m uvicorn main:app --reload
.\.venv\Scripts\python -m unittest -v test_backend test_acteurs test_informations_equipements
```

Documentation interactive : `http://localhost:8000/docs`.

Les tests CRUD exécutent les requêtes sur un graphe isolé via un transport Fuseki simulé, sans modifier le dataset réel.

Références : [endpoints Fuseki](https://jena.apache.org/documentation/fuseki2/fuseki-config-endpoint), [PhraseMatcher spaCy](https://spacy.io/usage/rule-based-matching).
