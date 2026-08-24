from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.app.bootstrap import get_services
from backend.app.services.chat_service import ChatHistoryTurn, ConversationState


router = APIRouter(prefix="/api", tags=["query"])


class QueryRequest(BaseModel):
    question: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatHistoryTurn] = []
    conversation_state: ConversationState | None = None


@router.post("/query")
def run_query(payload: QueryRequest, services=Depends(get_services)):
    return services["query_handler"](payload.question).model_dump()


@router.post("/chat")
def run_chat(payload: ChatRequest, services=Depends(get_services)):
    return services["chat_service"].reply(
        payload.message,
        payload.history,
        payload.conversation_state,
    ).model_dump()
