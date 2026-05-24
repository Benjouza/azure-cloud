"""
Foundry IQ / Knowledge Tool
Queries the Foundry IQ knowledge base (backed by Azure AI Search) for
policy documents, contracts, SLAs, SOPs, and procedures.

The Foundry IQ knowledge base is configured as a RemoteTool (MCP)
connection in the Foundry project. This module wraps the call with
error handling and provides a mock fallback for local development.

Requires: FOUNDRY_IQ_MCP_URL in environment
"""
from __future__ import annotations
import logging
import httpx

from ..config import settings
from ..models import KnowledgeResult

logger = logging.getLogger(__name__)

# Mock knowledge results for local development
_MOCK_KNOWLEDGE_RESPONSE = [
    {
        "source": "contracts/apex_supplier_master_agreement.md",
        "title": "Apex Manufacturing – Master Supply Agreement",
        "excerpt": (
            "Section 4.2 – Delivery Penalties: For shipments exceeding 10 calendar days past the "
            "confirmed delivery date, a penalty of 2% of the purchase order value per day applies, "
            "capped at 20%. Chronic non-performance (>50% late over any rolling 90-day window) "
            "triggers mandatory escalation to VP Supply Chain within 5 business days."
        ),
    },
    {
        "source": "policies/expedited_shipping_policy.md",
        "title": "Expedited Shipping Authorization Policy",
        "excerpt": (
            "Section 2.1 – Authorization Levels: Expedited shipping for orders exceeding $5,000 "
            "requires Director-level approval. For critical stockout situations (days of supply < 3), "
            "the Operations Director may authorize air freight at up to 3x standard shipping cost."
        ),
    },
    {
        "source": "policies/supplier_escalation_runbook.md",
        "title": "Supplier Performance Escalation Runbook",
        "excerpt": (
            "Step 3 – Escalation Threshold: If a supplier's on-time delivery rate falls below 50% "
            "in any 90-day period, initiate Tier 2 escalation: formal written notice, corrective "
            "action plan request within 10 business days, and alternate supplier qualification."
        ),
    },
    {
        "source": "policies/alternate_supplier_approval_policy.md",
        "title": "Alternate Supplier Qualification and Approval",
        "excerpt": (
            "Section 3.1 – Emergency Qualification: In stockout emergencies, pre-qualified alternate "
            "suppliers from the Approved Vendor List may be activated with Director approval and "
            "Quality Engineering sign-off within 48 hours."
        ),
    },
]


async def query_foundry_iq(question: str, user_context: dict) -> KnowledgeResult:
    """
    Query Foundry IQ for relevant knowledge documents.
    Falls back to mock data if the endpoint is not configured.
    """
    endpoint = settings.foundry_iq_mcp_url

    if not endpoint:
        logger.warning("FOUNDRY_IQ_MCP_URL not set — returning mock knowledge data")
        summary_parts = [f"• {doc['title']}: {doc['excerpt'][:100]}..." for doc in _MOCK_KNOWLEDGE_RESPONSE]
        return KnowledgeResult(
            success=True,
            documents=_MOCK_KNOWLEDGE_RESPONSE,
            summary="Relevant policies and contracts found:\n" + "\n".join(summary_parts),
        )

    try:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        token = credential.get_token("https://cognitiveservices.azure.com/.default")

        mcp_url = endpoint
        auth_headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Step 1: Initialize MCP session
            init_resp = await client.post(
                mcp_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "orchestrator-agent", "version": "0.1.0"},
                    },
                },
                headers=auth_headers,
            )
            logger.info(
                f"Foundry IQ MCP initialize: status={init_resp.status_code}, "
                f"body={init_resp.text[:500]}"
            )
            if init_resp.status_code >= 400:
                return KnowledgeResult(
                    success=False,
                    error=f"Foundry IQ MCP initialize failed ({init_resp.status_code}): {init_resp.text[:500]}",
                )

            session_id = init_resp.headers.get("mcp-session-id", "")
            session_headers = {**auth_headers}
            if session_id:
                session_headers["Mcp-Session-Id"] = session_id

            # Step 2: Send initialized notification
            await client.post(
                mcp_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                },
                headers=session_headers,
            )

            # Step 3: List available tools
            tools_resp = await client.post(
                mcp_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
                headers=session_headers,
            )
            logger.info(f"Foundry IQ MCP tools/list: status={tools_resp.status_code}, body={tools_resp.text[:500]}")

            if tools_resp.status_code >= 400:
                return KnowledgeResult(
                    success=False,
                    error=f"Foundry IQ MCP tools/list failed ({tools_resp.status_code}): {tools_resp.text[:500]}",
                )

            tools_data = tools_resp.json()
            tools = tools_data.get("result", {}).get("tools", [])
            tool_names = [t["name"] for t in tools]
            logger.info(f"Foundry IQ MCP tools available: {tool_names}")

            # Step 4: Call the appropriate tool
            target_tool = None
            for candidate in ["search", "query", "retrieve", "ask", "knowledge_search"]:
                if candidate in tool_names:
                    target_tool = candidate
                    break
            if not target_tool and tool_names:
                target_tool = tool_names[0]

            if not target_tool:
                return KnowledgeResult(success=False, error=f"No usable tools found. Available: {tool_names}")

            call_resp = await client.post(
                mcp_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": target_tool,
                        "arguments": {"question": question},
                    },
                },
                headers=session_headers,
            )
            logger.info(f"Foundry IQ MCP tools/call: status={call_resp.status_code}, body={call_resp.text[:500]}")

            if call_resp.status_code >= 400:
                return KnowledgeResult(
                    success=False,
                    error=f"Foundry IQ tool call failed ({call_resp.status_code}): {call_resp.text[:500]}",
                )

            call_data = call_resp.json()
            result_content = call_data.get("result", {}).get("content", [])

            documents = []
            summary_parts = []
            for item in result_content:
                if item.get("type") == "text":
                    text = item.get("text", "")
                    summary_parts.append(text)
                    documents.append({
                        "source": "foundry-iq",
                        "title": "Knowledge Result",
                        "excerpt": text,
                    })
                elif item.get("type") == "resource":
                    resource = item.get("resource", {})
                    documents.append({
                        "source": resource.get("uri", "foundry-iq"),
                        "title": resource.get("name", "Document"),
                        "excerpt": resource.get("text", str(resource)),
                    })

            summary = "\n".join(summary_parts) if summary_parts else str(call_data)

            return KnowledgeResult(
                success=True,
                documents=documents,
                summary=summary,
            )

    except BaseException as e:
        root_cause = e
        if hasattr(e, "exceptions"):
            root_cause = e.exceptions[0] if e.exceptions else e
        detail = str(root_cause)
        if hasattr(root_cause, "response"):
            try:
                detail += f" | Body: {root_cause.response.text}"
            except Exception:
                pass
        logger.error(f"Foundry IQ error: {detail}", exc_info=root_cause)
        return KnowledgeResult(success=False, error=detail)
