from fastapi import FastAPI, HTTPException
from SPARQLWrapper import SPARQLWrapper, JSON
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Smart Grid Semantic API", version="1.0")

# Autoriser les requêtes venant du Front-End ReactJS (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre en production (ex: ["http://localhost:3000"])
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# URL de l'endpoint SPARQL de votre serveur Apache Jena Fuseki
FUSEKI_ENDPOINT = "http://localhost:3030/smart-grid/sparql"

def execute_sparql_query(query: str):
    """Exécute une requête SPARQL sur le serveur Fuseki et retourne les résultats en JSON."""
    sparql = SPARQLWrapper(FUSEKI_ENDPOINT)
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    try:
        results = sparql.query().convert()
        return results["results"]["bindings"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur SPARQL : {str(e)}")

@app.get("/")
def read_root():
    return {"message": "API Backend Python pour le Système Électrique Intelligent"}





# ==================== PARTIE : ÉQUIPEMENTS / SOURCES ====================

@app.get("/api/equipements")
def get_equipements():
    """Route pour récupérer la liste des équipements (sources de production) depuis l'ontologie RDF"""
    query = """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX esg: <https://example.org/energie-smart-grid#>

        SELECT ?source ?propriete ?valeur
        WHERE {
            ?source rdf:type esg:SourceProduction ;
                    ?propriete ?valeur .
        }
    """
    bindings = execute_sparql_query(query)
    
    equipements = []
    for row in bindings:
        equipements.append({
            "uri": row.get("source", {}).get("value"),
            "property": row.get("propriete", {}).get("value"),
            "value": row.get("valeur", {}).get("value")
        })
        
    return {"equipements": equipements}