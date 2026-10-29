"""API du module Gestion de la production et du stockage."""
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

if __package__:
    from . import repository, nlp
else:
    import repository
    import nlp

# Variables de connexion : modifiables ici ou via l'environnement.
FUSEKI_BASE_URL = os.getenv("FUSEKI_BASE_URL", "http://localhost:3030").rstrip("/")
FUSEKI_DATASET = os.getenv("FUSEKI_DATASET", "smart-grid").strip("/")
FUSEKI_ENDPOINT = os.getenv("FUSEKI_QUERY_URL", f"{FUSEKI_BASE_URL}/{FUSEKI_DATASET}/sparql")
FUSEKI_UPDATE_ENDPOINT = os.getenv("FUSEKI_UPDATE_URL", f"{FUSEKI_BASE_URL}/{FUSEKI_DATASET}/update")
FUSEKI_USERNAME = os.getenv("FUSEKI_USERNAME", "")
FUSEKI_PASSWORD = os.getenv("FUSEKI_PASSWORD", "")
FUSEKI_TIMEOUT = float(os.getenv("FUSEKI_TIMEOUT", "15"))
RDF_NAMESPACE = repository.NAMESPACE

store = repository.Store(FUSEKI_ENDPOINT, FUSEKI_UPDATE_ENDPOINT,
                         FUSEKI_USERNAME, FUSEKI_PASSWORD, FUSEKI_TIMEOUT)
app = FastAPI(title="Smart Grid Semantic API - Production & Storage", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(","),
    allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"],
)
Collection = Literal["installations", "reserves", "reseaux", "infrastructures"]


class Resource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    type: str | None = None
    label: str | None = None
    properties: dict = Field(default_factory=dict)


class Prompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=2000)
    execute: bool = True


@app.get("/")
def root():
    return {"message": "Gestion de la production et du stockage", "docs": "/docs"}


@app.get("/api/schema")
def schema():
    return repository.public_schema()


@app.get("/api/health")
def health():
    return {"fuseki": "ok", "accessible": store.query("ASK {}")["boolean"]}


@app.post("/api/nlp")
def natural_language(body: Prompt):
    return store.run(nlp.translate(body.prompt), execute=body.execute)


# Route existante conservée pour les autres modules.
def execute_sparql_query(query: str):
    return store.query(query)["results"]["bindings"]


@app.get("/api/equipements")
def get_equipements():
    rows = execute_sparql_query(repository.PREFIXES + """
        SELECT ?source ?propriete ?valeur WHERE {
          ?source rdf:type/rdfs:subClassOf* eg:SourceProduction ; ?propriete ?valeur .
        }
    """)
    return {"equipements": [{"uri": r["source"]["value"], "property": r["propriete"]["value"],
                              "value": r["valeur"]["value"]} for r in rows]}


@app.get("/api/{collection}")
def list_resources(collection: Collection, type: str | None = None,
                   search: str | None = None, limit: int = Query(50, ge=1, le=200),
                   offset: int = Query(0, ge=0)):
    return store.run(dict(action="read", collection=collection, type=type,
                          search=search, limit=limit, offset=offset))


@app.get("/api/{collection}/{resource_id}")
def get_resource(collection: Collection, resource_id: str):
    return store.run(dict(action="read", collection=collection, id=resource_id))


@app.post("/api/{collection}", status_code=201)
def create_resource(collection: Collection, body: Resource):
    if not body.id or not body.type:
        raise HTTPException(422, "id et type sont obligatoires pour la création.")
    return store.run(dict(action="create", collection=collection, **body.model_dump()))


@app.patch("/api/{collection}/{resource_id}")
def update_resource(collection: Collection, resource_id: str, body: Resource):
    if body.id is not None or body.type is not None:
        raise HTTPException(422, "L'identifiant et la classe ne sont pas modifiables.")
    return store.run(dict(action="update", collection=collection, id=resource_id,
                          **body.model_dump(exclude={"id", "type"})))


@app.delete("/api/{collection}/{resource_id}")
def delete_resource(collection: Collection, resource_id: str):
    return store.run(dict(action="delete", collection=collection, id=resource_id))
