"""Routes HTTP du module Gestion des acteurs et des organisations (préfixe /api/acteurs)."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

if __package__:
    from . import acteurs_nlp as nlp, acteurs_repository as repo
else:
    import acteurs_nlp as nlp
    import acteurs_repository as repo

Collection = Literal["personnes", "organisations"]


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
    acteurs = repo.Acteurs(store)
    router = APIRouter(prefix="/api/acteurs", tags=["Acteurs et organisations"])

    @router.get("/schema")
    def schema():
        return repo.schema()

    @router.get("/stats")
    def stats():
        return acteurs.stats()

    @router.get("/lookup")
    def lookup(cls: str, q: str = "", limit: int = Query(30, ge=1, le=200)):
        return acteurs.lookup(cls, q, limit)

    @router.post("/nlp")
    def natural_language(body: Prompt):
        plan = nlp.translate(body.prompt)
        return {**acteurs.run(plan, body.execute), "explain": nlp.explain(plan)}

    @router.get("/{collection}")
    def list_resources(collection: Collection, type: str | None = None, search: str | None = None,
                       issue: str | None = None, filter: list[str] = Query([]),
                       limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        # filter=propriete:valeur (relation ou valeur exacte), répétable.
        filters = [{"property": p, "operator": "=", "value": v} for p, _, v in (f.partition(":") for f in filter)]
        return acteurs.run(dict(action="read", collection=collection, types=[type] if type else None,
                                search=search, issue=issue, filters=filters, limit=limit, offset=offset))

    @router.get("/{collection}/{resource_id}")
    def get_resource(collection: Collection, resource_id: str):
        return acteurs.run(dict(action="read", collection=collection, id=resource_id))

    @router.get("/{collection}/{resource_id}/relations")
    def get_relations(collection: Collection, resource_id: str):
        return acteurs.relations(collection, resource_id)

    @router.post("/{collection}", status_code=201)
    def create_resource(collection: Collection, body: Resource):
        if not body.id:
            raise HTTPException(422, "id est obligatoire pour la création.")
        return acteurs.run(dict(action="create", collection=collection, **body.model_dump()))

    @router.patch("/{collection}/{resource_id}")
    def update_resource(collection: Collection, resource_id: str, body: Resource):
        if body.id is not None or body.type is not None:
            raise HTTPException(422, "L'identifiant et la classe ne sont pas modifiables.")
        return acteurs.run(dict(action="update", collection=collection, id=resource_id,
                                **body.model_dump(exclude={"id", "type"})))

    @router.delete("/{collection}/{resource_id}")
    def delete_resource(collection: Collection, resource_id: str):
        return acteurs.run(dict(action="delete", collection=collection, id=resource_id))

    return router
