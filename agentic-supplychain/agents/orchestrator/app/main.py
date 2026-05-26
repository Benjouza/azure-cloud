"""
Agentic Supply Chain Orchestrator – Hosted Agent Entrypoint
Uses the official azure-ai-agentserver-invocations SDK to implement
the Foundry Hosted Agent "invocations" protocol.
"""
import json
import logging
import sys

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Configure logging to output to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
    force=True,
)

from .orchestrator import handle_query

# Create the invocations host server (handles /readiness, session, etc.)
app = InvocationAgentServerHost()


@app.invoke_handler
async def handle_invoke(request: Request) -> Response:
    """Handle an invocation request from the Foundry platform."""
    data = await request.json()
    session_id: str = request.state.session_id

    # Extract user message — SDK convention uses "message",
    # but also support "input" for flexibility
    user_message = (
        data.get("message")
        or data.get("input")
        or data.get("question")
        or data.get("content", "")
    )

    if not user_message:
        return Response(content="Missing 'message' in request", status_code=400)

    print(f"=== INVOCATION ===")
    print(f"Session: {session_id}")
    print(f"Message: {user_message!r}")

    try:
        result = await handle_query(user_query=user_message, user_context={})
    except Exception as e:
        logging.getLogger(__name__).error(f"handle_query failed: {e}", exc_info=True)
        return JSONResponse(
            {
                "status": "failed",
                "error": {"type": "server_error", "message": f"Error processing request: {str(e)}"},
            },
            status_code=500,
        )

    # Format human-readable response
    response_text = _format_response_text(result)

    print(f"=== RESPONSE ===")
    print(f"Route: {result.route}")
    print(f"Text: {response_text[:500]}")
    print(f"=== END ===")

    # Foundry Playground UI expects the OpenAI Responses API format
    return JSONResponse({
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": response_text}
                ],
            }
        ],
    })


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


if __name__ == "__main__":
    app.run()
