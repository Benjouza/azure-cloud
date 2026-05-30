"""
FastAPI HTTP server for the PetStore Supply Chain Orchestrator Agent.
Exposes a /chat endpoint that routes queries through the Foundry agent.
"""

import contextlib
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.agent import create_orchestrator_agent, run_query, cleanup

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Lifespan – create agent once on startup, clean up on shutdown               #
# --------------------------------------------------------------------------- #
project_client = None
openai_client = None
agent = None
conversation = None


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global project_client, openai_client, agent, conversation
    logger.info("Starting up – provisioning agent...")
    project_client, openai_client, agent, conversation = create_orchestrator_agent()
    logger.info("Agent ready.")
    yield
    logger.info("Shutting down – deleting agent version...")
    try:
        cleanup(project_client, agent)
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")


app = FastAPI(
    title="PetStore Supply Chain Orchestrator Agent",
    version="2.0.0",
    lifespan=lifespan,
)


# --------------------------------------------------------------------------- #
# Request / Response models                                                   #
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    agent_name: str


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok", "agent": agent.name if agent else "not initialised"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not agent or not openai_client or not conversation:
        raise HTTPException(status_code=503, detail="Agent not initialised")
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    try:
        response_text = run_query(openai_client, agent, conversation, req.message)
    except Exception as e:
        logger.error(f"run_query failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))

    return ChatResponse(
        response=response_text,
        conversation_id=conversation.id,
        agent_name=agent.name,
    )
