# Module Gestion des acteurs et des organisations (Souhir)

Tables : **personnes** (`Personne` et sous-classes : techniciens, responsables, usagers, occupants…) et **organisations** (`Organisation` et sous-classes : gestionnaires, services, équipes de maintenance, centres…).

Fichiers ajoutés (aucun fichier d'un autre module n'est modifié, sauf 3 lignes dans `main.py` qui enregistrent les routes) :

| Fichier | Rôle |
| --- | --- |
| `acteurs_repository.py` | Construction SPARQL, validation, CRUD, relations, statistiques |
| `acteurs_nlp.py` | spaCy : phrase française → plan (action, table, classes, filtres) |
| `acteurs_routes.py` | Routes FastAPI sous `/api/acteurs` |
| `test_acteurs.py` | Tests sur un graphe RDF isolé |

La connexion Fuseki réutilise les variables déjà définies au début de `main.py`.

## Routes

| Méthode | Route | Fonction |
| --- | --- | --- |
| GET | `/api/acteurs/{personnes|organisations}` | Lister : `type`, `search`, `issue`, `filter=propriete:valeur`, `limit`, `offset` |
| GET | `/api/acteurs/{collection}/{id}` | Lire une ressource |
| GET | `/api/acteurs/{collection}/{id}/relations` | Ressources liées dans les deux sens |
| POST | `/api/acteurs/{collection}` | Créer `{id, type, label, properties}` |
| PATCH | `/api/acteurs/{collection}/{id}` | Modifier `{label, properties}` (`[]` retire une propriété) |
| DELETE | `/api/acteurs/{collection}/{id}` | Supprimer la ressource et ses liens entrants |
| POST | `/api/acteurs/nlp` | `{prompt, execute}` : traduit en SPARQL ; `execute:false` = aperçu sans écriture |
| GET | `/api/acteurs/schema` | Classes et propriétés (le frontend génère ses formulaires dessus) |
| GET | `/api/acteurs/stats` | Totaux, répartition par classe, contrôles qualité |
| GET | `/api/acteurs/lookup?cls=Organisation&q=` | Liste {id, name} pour les champs de relation |

Contrôles qualité (`issue`) : `sans_nom`, `sans_identifiant`, `sans_organisation` (personnes) ; `sans_employe`, `sans_collaboration` (organisations). Les relations `travaillePour` / `emploiePersonne` sont cherchées dans les deux sens.

## Phrases comprises

```text
Affiche les personnes / les organisations
Liste les techniciens          (les sous-classes sont incluses)
Affiche les responsables       (groupe de classes : ResponsableSecteurUrbain, ResponsableSiteSolaire…)
Quels techniciens travaillent pour service_distribution_ariana ?
Affiche les personnes nommées Salma
Liste les organisations qui collaborent avec service_distribution_ariana
Combien de personnes sans organisation ?
Organisations sans employé
Affiche les gestionnaires créés après 2000
Crée un technicien nomComplet="Ali Ben" travaillePour=service_distribution_ariana
Modifie la personne id=ali_ben etatService="en congé"
Supprime la personne id=ali_ben
```

Pour une création sans `id=`, l'identifiant est généré à partir du nom. Les modifications et suppressions exigent `id=`. Les phrases non comprises renvoient 422 avec la liste des mots non reconnus.

## Lancer

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn main:app --reload
.venv\Scripts\python -m unittest -v test_acteurs
```
