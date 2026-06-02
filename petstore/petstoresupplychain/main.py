"""
PetStore Supply Chain Orchestrator — Foundry Hosted Agent
Entry point: python main.py
Uses stdlib http.server (zero external deps for startup).
Azure SDK imported lazily on first invocation.
"""

import json
import logging
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("petstoresupplychain")

_endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT") or os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
_model = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o")
logger.info("Config: endpoint=%s, model=%s", _endpoint, _model)

# Lazy-initialized on first invocation
_openai_client = None
_sessions: dict[str, list[dict[str, str]]] = {}

_SYSTEM_PROMPT = """You are the PetStore Supply Chain Orchestrator Agent.

Your job is to classify every incoming user message into one of two intents and
route it to the correct tool:

## Intent: DATA_QUERY
Use the **Microsoft Fabric** tool when the user asks about:
- Product inventory levels, stock quantities, warehouse data
- Order status, shipment tracking, delivery ETAs
- Supplier performance metrics, lead times
- Retailer orders, fulfillment status
- Pet product catalog information (food, toys, accessories, health)
- Any structured data lookup from the petstore supply-chain database

## Intent: POLICY_KNOWLEDGE
Use the **Azure AI Search** tool when the user asks about:
- Pet product return and refund policies
- Supplier onboarding and qualification procedures
- Product recall and safety compliance policies
- Retail partner program guidelines
- Shipping and fulfillment SOPs
- Any knowledge-base / document retrieval question

Always explain which source you used and cite relevant details in your answer.
If a query spans both intents, call both tools and synthesize the results.
"""


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        logger.info("Initializing Azure credentials and OpenAI client...")
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
        project_client = AIProjectClient(endpoint=_endpoint, credential=credential)
        _openai_client = project_client.get_openai_client()
        logger.info("OpenAI client initialized successfully.")
    return _openai_client


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/readiness":
            self._send_json(200, {"status": "healthy"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/invocations":
            # Log all incoming headers for debugging
            logger.info("Request headers: %s", dict(self.headers))
            self._handle_invocation(parsed)
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_invocation(self, parsed):
        # Read request body
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        logger.info("Invocation received: %s", body[:500])

        # Parse session ID from query params
        params = parse_qs(parsed.query)
        session_id = (params.get("agent_session_id") or ["default"])[0]

        # Get invocation ID from header
        invocation_id = self.headers.get("x-agent-invocation-id", "")

        # Extract user message
        try:
            data = json.loads(body)
            user_message = ""
            if isinstance(data, dict):
                user_message = data.get("input") or data.get("message") or ""
                if not user_message:
                    messages = data.get("messages", [])
                    for msg in reversed(messages):
                        if msg.get("role") == "user":
                            user_message = msg.get("content", "")
                            break
            if not user_message:
                self._send_json(400, {"error": "No input/message found"})
                return
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON"})
            return

        logger.info("Processing (session %s): %s", session_id, user_message[:200])

        # Get or create session history
        if session_id not in _sessions:
            _sessions[session_id] = []
        history = _sessions[session_id]
        history.append({"role": "user", "content": user_message})

        # Call the model
        try:
            client = _get_openai_client()
            response = client.responses.create(
                model=_model,
                instructions=_SYSTEM_PROMPT,
                input=list(history),
                store=False,
            )
            result = response.output_text
            history.append({"role": "assistant", "content": result})
            logger.info("=== MODEL RESPONSE ===")
            logger.info(result)
            logger.info("=== END RESPONSE (%d chars) ===", len(result))
        except Exception as e:
            logger.error("Model call failed: %s", e, exc_info=True)
            result = f"Error: {e}"

        # Respond with protocol headers — try plain text for portal rendering
        resp_body = result.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(resp_body)))
        if invocation_id:
            self.send_header("x-agent-invocation-id", invocation_id)
        self.send_header("x-agent-session-id", session_id)
        self.end_headers()
        self.wfile.write(resp_body)

    def _send_json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        logger.info("[HTTP] %s", format % args)


if __name__ == "__main__":
    logger.info("Starting HTTP server on 0.0.0.0:8088...")
    server = HTTPServer(("0.0.0.0", 8088), Handler)
    logger.info("Server ready on port 8088")
    server.serve_forever()
