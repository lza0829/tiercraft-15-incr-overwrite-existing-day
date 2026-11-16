from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import pipeline

router = APIRouter(tags=["主题域"])


class ModeBody(BaseModel):
    load_mode: str = Field(..., description="增量 incremental / 全量 full")


@router.get("/domains")
def list_domains():
    return pipeline.list_domains()


@router.get("/domains/{domain_id}")
def get_domain(domain_id: int):
    d = pipeline.get_domain(domain_id)
    if not d:
        raise HTTPException(status_code=404, detail="主题域不存在")
    return d


@router.put("/domains/{domain_id}/load-mode")
def set_load_mode(domain_id: int, body: ModeBody):
    try:
        return pipeline.set_load_mode(domain_id, body.load_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
