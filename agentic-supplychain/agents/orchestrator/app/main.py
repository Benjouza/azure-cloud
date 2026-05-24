"""
Agentic Supply Chain Orchestrator – FastAPI Entrypoint
Serves the orchestrator as an HTTP service for local testing
and as the hosted agent container entrypoint.

Implements the Foundry Hosted Agent "invocations" protocol:
  - GET  /readiness        → 200 when ready
  - POST /invocations      → execute agent logic
  - GET  /invocations/docs/openapi.json → OpenAPI spec
"""
import uuid
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .models import QueryRequest, SynthesizedResponse, HealthResponse
from .orchestrator import handle_query

app = FastAPI(
    title="Agentic Supply Chain Orchestrator",
    description="Hosted agent orchestrator that combines Fabric structured data with Foundry IQ knowledge.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/readiness")
async def readiness():
    """Readiness probe for Foundry hosted agent platform."""
    return {"status": "ready"}


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint for container probes."""
    return HealthResponse(
        status="ok",
        agent_name=settings.agent_name,
        version="0.1.0",
    )


@app.post("/invocations")
async def invocations(request: Request):
    """
    Foundry Invocations protocol endpoint.
    Accepts {"input": "user question"} or {"question": "..."} payloads.
    """
    import json
    import re
    import logging

    raw_body = await request.body()
    content_type = request.headers.get("content-type", "")
    body_text = raw_body.decode("utf-8", errors="replace").strip()

    # Platform may send text/plain with trailing quotes or whitespace — clean up
    body_text = body_text.strip("'\"` \t\n\r")

    body = None
    # Try parsing as JSON (may have been wrapped in quotes or have trailing chars)
    for candidate in [body_text, raw_body]:
        try:
            body = json.loads(candidate)
            break
        except (json.JSONDecodeError, ValueError, TypeError):
            continue

    if body is None:
        # Try to find JSON object within the text
        json_match = re.search(r'\{[^{}]*\}', body_text)
        if json_match:
            try:
                body = json.loads(json_match.group(0))
            except (json.JSONDecodeError, ValueError):
                pass

    if body is None:
        # Last resort: extract input value with regex
        logging.getLogger(__name__).warning(
            f"Non-standard request body. Content-Type: {content_type}, "
            f"Body (first 500 chars): {body_text[:500]}"
        )
        match = re.search(r'"input"\s*:\s*"([^"]+)"', body_text)
        if match:
            body = {"input": match.group(1)}
        else:
            # Treat the entire body as the user's question
            body = {"input": body_text}

    # Extract the user question from various payload formats
    question = (
        body.get("input")
        or body.get("question")
        or body.get("message")
        or body.get("content", "")
    )
    user_context = body.get("user_context", body.get("context", {}))

    invocation_id = request.headers.get(
        "x-agent-invocation-id", str(uuid.uuid4())
    )

    logging.getLogger(__name__).info(
        f"Invocation {invocation_id}: extracted question={question[:200]!r}, "
        f"route will be determined by orchestrator"
    )

    try:
        result = await handle_query(user_query=question, user_context=user_context)
    except Exception as e:
        logging.getLogger(__name__).error(f"Invocation {invocation_id}: handle_query failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "invocation_id": invocation_id,
                "status": "error",
                "error": str(e),
            },
            headers={"x-agent-invocation-id": invocation_id},
        )

    output = result.model_dump()
    logging.getLogger(__name__).info(
        f"Invocation {invocation_id}: completed, route={output.get('route')}, "
        f"findings_len={len(output.get('findings', ''))}, "
        f"actions_count={len(output.get('recommended_actions', []))}"
    )

    # Format a human-readable response for the platform chat UI
    response_text = _format_response_text(result)

    return JSONResponse(
        content={
            "invocation_id": invocation_id,
            "status": "completed",
            "output": response_text,
        },
        headers={
            "x-agent-invocation-id": invocation_id,
        },
    )


def _format_response_text(result) -> str:
    """Format SynthesizedResponse as readable text for the chat UI."""
    parts = []

    if result.findings and result.findings != "No structured data available.":
        parts.append(f"**Findings:**\n{result.findings}")

    if result.policy_implications and result.policy_implications != "No policy data available.":
        parts.append(f"**Policy Implications:**\n{result.policy_implications}")

    if result.recommended_actions:
        actions_text = "\n".join(f"• {a}" for a in result.recommended_actions)
        parts.append(f"**Recommended Actions:**\n{actions_text}")

    if result.supporting_evidence:
        evidence_text = "\n".join(f"- {e}" for e in result.supporting_evidence)
        parts.append(f"**Supporting Evidence:**\n{evidence_text}")

    if not parts:
        return "I wasn't able to find relevant information for your question. Please try rephrasing."

    return "\n\n".join(parts)


@app.post("/query", response_model=SynthesizedResponse)
async def query(request: QueryRequest):
    """
    Accept a business question, route to appropriate tools,
    and return a synthesized grounded answer.
    """
    return await handle_query(
        user_query=request.question,
        user_context=request.user_context,
    )


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
