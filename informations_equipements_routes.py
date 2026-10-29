"""CRUD RDF et demandes spaCy du module Informations et équipements."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

if __package__:
    from . import nlp, repository
else:
    import nlp
    import repository

Collection = Literal["equipements", "informations"]


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


def build_router(store):
    router = APIRouter(prefix="/api/gestion-informations-equipements",
                       tags=["Gestion des informations et des équipements"])

    @router.get("/schema")
    def schema():
        full = repository.public_schema()
        return {"namespace": full["namespace"], "collections": {
            name: full["collections"][name] for name in ("equipements", "informations")}}

    @router.post("/nlp")
    def natural_language(body: Prompt):
        plan = nlp.translate(body.prompt)
        if plan["collection"] not in ("equipements", "informations"):
            raise HTTPException(422, "Cette demande doit concerner les équipements ou les informations.")
        return store.run(plan, execute=body.execute)

    @router.get("/{collection}")
    def list_resources(collection: Collection, type: str | None = None,
                       search: str | None = None, limit: int = Query(50, ge=1, le=200),
                       offset: int = Query(0, ge=0)):
        return store.run(dict(action="read", collection=collection, type=type,
                             search=search, limit=limit, offset=offset))

    @router.get("/{collection}/{resource_id}")
    def get_resource(collection: Collection, resource_id: str):
        return store.run(dict(action="read", collection=collection, id=resource_id))

    @router.post("/{collection}", status_code=201)
    def create_resource(collection: Collection, body: Resource):
        if not body.id or not body.type:
            raise HTTPException(422, "id et type sont obligatoires pour la création.")
        return store.run(dict(action="create", collection=collection, **body.model_dump()))

    @router.patch("/{collection}/{resource_id}")
    def update_resource(collection: Collection, resource_id: str, body: Resource):
        if body.id is not None or body.type is not None:
            raise HTTPException(422, "L'identifiant et la classe ne sont pas modifiables.")
        return store.run(dict(action="update", collection=collection, id=resource_id,
                             **body.model_dump(exclude={"id", "type"})))

    @router.delete("/{collection}/{resource_id}")
    def delete_resource(collection: Collection, resource_id: str):
        return store.run(dict(action="delete", collection=collection, id=resource_id))

    return router
