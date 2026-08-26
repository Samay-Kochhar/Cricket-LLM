from __future__ import annotations

from fastapi import APIRouter, Depends
from typing import Literal

from pydantic import BaseModel, Field

from backend.app.bootstrap import get_services
from backend.app.services.chat_service import ChatHistoryTurn, ConversationState


router = APIRouter(prefix="/api", tags=["query"])


class QueryRequest(BaseModel):
    question: str


class MatchupRequest(BaseModel):
    batter: str = Field(min_length=1)
    bowler: str = Field(min_length=1)
    phase: Literal["all", "powerplay", "middle", "death"] = "all"
    year: int | None = Field(default=None, ge=1971, le=2100)
    venue: str | None = None


class ChatRequest(BaseModel):
    message: str
    history: list[ChatHistoryTurn] = []
    conversation_state: ConversationState | None = None


@router.post("/query")
def run_query(payload: QueryRequest, services=Depends(get_services)):
    return services["query_handler"](payload.question).model_dump()


@router.post("/matchups")
def run_matchup(payload: MatchupRequest, services=Depends(get_services)):
    result = services["matchup_handler"](**payload.model_dump())
    return {key: response.model_dump() for key, response in result.items()}


@router.post("/chat")
def run_chat(payload: ChatRequest, services=Depends(get_services)):
    return services["chat_service"].reply(
        payload.message,
        payload.history,
        payload.conversation_state,
    ).model_dump()
