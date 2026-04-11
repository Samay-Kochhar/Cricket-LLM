from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.app.bootstrap import get_services


router = APIRouter(prefix="/api", tags=["query"])


class QueryRequest(BaseModel):
    question: str


@router.post("/query")
def run_query(payload: QueryRequest, services=Depends(get_services)):
    return services["query_handler"](payload.question).model_dump()
