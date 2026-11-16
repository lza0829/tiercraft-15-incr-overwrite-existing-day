from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import pipeline

router = APIRouter(tags=["分层"])


class LoadBody(BaseModel):
    domain_id: int = Field(..., description="主题域编号")


@router.get("/layers/counts")
def counts(domain_id: int | None = Query(default=None)):
    return pipeline.layer_counts(domain_id)


@router.get("/layers/paste/day-counts")
def paste_day_counts(domain_id: int = Query(...)):
    try:
        return pipeline.paste_day_counts(domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/layers/paste/load")
def load_paste(body: LoadBody):
    try:
        # 失败也已经落任务记录，直接返回报告由界面展示失败原因。
        return pipeline.load_paste(body.domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/layers/{layer}")
def list_layer(layer: str, domain_id: int | None = Query(default=None)):
    mapping = {"paste": "paste", "detail": "detail", "summary": "summary",
               "贴源": "paste", "明细": "detail", "汇总": "summary"}
    key = mapping.get(layer)
    if not key:
        raise HTTPException(status_code=400, detail="分层只能是贴源/明细/汇总")
    try:
        return pipeline.layer_rows(key, domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
