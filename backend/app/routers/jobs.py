from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import pipeline

router = APIRouter(tags=["分层任务"])


class JobBody(BaseModel):
    domain_id: int = Field(..., description="主题域编号")


@router.get("/jobs")
def list_jobs(domain_id: int | None = None):
    return pipeline.list_jobs(domain_id)


@router.get("/load-verdicts/by-job/{job_id}")
def verdict_by_job(job_id: int):
    """按任务 id 只读查询装载裁决证明（模式、写入日、跳过日、下游是否待重跑）。"""
    verdict = pipeline.get_verdict_by_job(job_id)
    if not verdict:
        raise HTTPException(status_code=404, detail="该任务没有装载裁决证明")
    return verdict


@router.get("/load-verdicts")
def list_verdicts(domain_id: int | None = Query(default=None)):
    return pipeline.list_verdicts(domain_id)


@router.post("/jobs/paste-to-detail")
def paste_to_detail(body: JobBody):
    try:
        return pipeline.run_paste_to_detail(body.domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/detail-to-summary")
def detail_to_summary(body: JobBody):
    try:
        return pipeline.run_detail_to_summary(body.domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
