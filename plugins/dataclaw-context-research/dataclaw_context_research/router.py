"""API routes for context research findings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dataclaw_context_research.tools import (
    context_research_build_program,
    context_research_generate_queries,
    context_research_list_findings,
    context_research_list_programs,
    context_research_run_parallel_experiments,
    context_research_save_program_to_okf,
    context_research_save_to_okf,
    context_research_search_sources,
    context_research_summarize_findings,
)

router = APIRouter()


class QueryRequest(BaseModel):
    dataset_id: str = ""
    problem_statement: str = ""
    limit: int = 8


class SourceSearchRequest(BaseModel):
    query: str
    sources: list[str] | None = None
    dataset_id: str = ""
    problem_statement: str = ""
    limit: int = 8


class SaveToOKFRequest(BaseModel):
    bundle_id: str
    dataset_id: str = ""
    finding_ids: list[str] | None = None


class BuildProgramRequest(BaseModel):
    dataset_id: str = ""
    problem_statement: str = ""
    finding_ids: list[str] | None = None
    max_hypotheses: int = 8


class SaveProgramToOKFRequest(BaseModel):
    bundle_id: str
    program_id: str


class RunParallelExperimentsRequest(BaseModel):
    program_id: str
    subagent_names: list[str]
    max_tasks: int = 4


@router.post("/queries")
async def generate_queries_route(req: QueryRequest) -> dict[str, Any]:
    try:
        return await context_research_generate_queries(
            dataset_id=req.dataset_id,
            problem_statement=req.problem_statement,
            limit=req.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/sources/search")
async def search_sources_route(req: SourceSearchRequest) -> dict[str, Any]:
    return await context_research_search_sources(
        query=req.query,
        sources=req.sources,
        dataset_id=req.dataset_id,
        problem_statement=req.problem_statement,
        limit=req.limit,
    )


@router.get("/findings")
async def list_findings_route(dataset_id: str = "", limit: int = 20) -> dict[str, Any]:
    return await context_research_list_findings(dataset_id=dataset_id, limit=limit)


@router.get("/findings/summary")
async def summarize_findings_route(dataset_id: str = "") -> dict[str, Any]:
    return await context_research_summarize_findings(dataset_id=dataset_id)


@router.post("/okf")
async def save_to_okf_route(req: SaveToOKFRequest) -> dict[str, Any]:
    try:
        return await context_research_save_to_okf(
            bundle_id=req.bundle_id,
            dataset_id=req.dataset_id,
            finding_ids=req.finding_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/programs")
async def build_program_route(req: BuildProgramRequest) -> dict[str, Any]:
    try:
        return await context_research_build_program(
            dataset_id=req.dataset_id,
            problem_statement=req.problem_statement,
            finding_ids=req.finding_ids,
            max_hypotheses=req.max_hypotheses,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/programs")
async def list_programs_route(dataset_id: str = "", limit: int = 20) -> dict[str, Any]:
    return await context_research_list_programs(dataset_id=dataset_id, limit=limit)


@router.post("/programs/okf")
async def save_program_to_okf_route(req: SaveProgramToOKFRequest) -> dict[str, Any]:
    try:
        return await context_research_save_program_to_okf(
            bundle_id=req.bundle_id,
            program_id=req.program_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/programs/run-parallel")
async def run_parallel_experiments_route(req: RunParallelExperimentsRequest) -> dict[str, Any]:
    try:
        return await context_research_run_parallel_experiments(
            program_id=req.program_id,
            subagent_names=req.subagent_names,
            max_tasks=req.max_tasks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
