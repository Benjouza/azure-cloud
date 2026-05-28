"""
Fabric Data Agent Tool
Queries the Microsoft Fabric data agent for structured supply chain analytics.

The Fabric data agent exposes an MCP (Model Context Protocol) server endpoint.
This module connects via SSE transport and invokes the agent's tools.

Requires: FABRIC_DATA_AGENT_ENDPOINT in environment
"""
from __future__ import annotations
import logging

from ..config import settings
from ..models import FabricResult

logger = logging.getLogger(__name__)

_AUTH_ERROR_HINTS = (
    "authorization",
    "unauthorized",
    "forbidden",
    "permission",
    "access denied",
    "not allowed",
)

# Mock data for local development when Fabric is not connected
_MOCK_FABRIC_RESPONSE = {
    "suppliers_with_delays": [
        {"supplier_id": "SUP-003", "name": "Apex Manufacturing", "region": "Northeast",
         "avg_delay_days": 12.4, "late_shipment_pct": 0.68, "total_orders": 47},
        {"supplier_id": "SUP-007", "name": "Delta Components", "region": "Northeast",
         "avg_delay_days": 4.2, "late_shipment_pct": 0.22, "total_orders": 31},
    ],
    "at_risk_inventory": [
        {"warehouse": "WH-NE-01", "product": "PRD-110", "product_name": "Industrial Valve Assembly",
         "current_qty": 12, "reorder_point": 50, "days_of_supply": 2.1, "status": "CRITICAL"},
        {"warehouse": "WH-NE-01", "product": "PRD-205", "product_name": "Precision Bearing Kit",
         "current_qty": 28, "reorder_point": 40, "days_of_supply": 5.8, "status": "LOW"},
    ],
    "summary": (
        "Apex Manufacturing (SUP-003) has the highest delay rate in the Northeast at 68% late shipments "
        "with an average delay of 12.4 days across 47 orders. Warehouse WH-NE-01 has 2 products at risk: "
        "Industrial Valve Assembly is CRITICAL with only 2.1 days of supply remaining."
    ),
}


async def query_fabric_agent(question: str, user_context: dict) -> FabricResult:
    """
    Send a natural-language question to the Fabric data agent via MCP protocol.
    Falls back to mock data if the endpoint is not configured.
    """
    endpoint = settings.fabric_data_agent_endpoint

    if not endpoint:
        logger.warning("FABRIC_DATA_AGENT_ENDPOINT not set — returning mock data")
        return FabricResult(
            success=True,
            data=_MOCK_FABRIC_RESPONSE,
            summary=_MOCK_FABRIC_RESPONSE["summary"],
        )

    try:
        from azure.identity import DefaultAzureCredential
        import httpx

        credential = DefaultAzureCredential()
        token = credential.get_token("https://api.fabric.microsoft.com/.default")

        mcp_url = endpoint
        auth_headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        logger.info("Fabric token acquired for scope https://api.fabric.microsoft.com/.default")

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
                        "clientInfo": {"name": "supplychain-orchestrator-agent", "version": "0.1.0"},
                    },
                },
                headers=auth_headers,
            )
            logger.info(
                f"Fabric MCP initialize: status={init_resp.status_code}, "
                f"headers={dict(init_resp.headers)}, body={init_resp.text[:500]}"
            )
            if init_resp.status_code >= 400:
                return FabricResult(
                    success=False,
                    error=f"Fabric MCP initialize failed ({init_resp.status_code}): {init_resp.text[:500]}",
                )

            init_data = init_resp.json()
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
            logger.info(f"Fabric MCP tools/list: status={tools_resp.status_code}, body={tools_resp.text[:500]}")

            if tools_resp.status_code >= 400:
                return FabricResult(
                    success=False,
                    error=f"Fabric MCP tools/list failed ({tools_resp.status_code}): {tools_resp.text[:500]}",
                )

            tools_data = tools_resp.json()
            tools = tools_data.get("result", {}).get("tools", [])
            tool_names = [t["name"] for t in tools]
            logger.info(f"Fabric MCP tools available: {tool_names}")

            # Step 4: Call the appropriate tool with correct argument name
            target_tool = None
            target_tool_schema = {}
            for candidate in [
                "DataAgent_supplychain_data_agent",
                "query", "ask", "chat", "execute_query", "run_query",
            ]:
                if candidate in tool_names:
                    target_tool = candidate
                    target_tool_schema = next((t.get("inputSchema", {}) for t in tools if t["name"] == candidate), {})
                    break
            if not target_tool and tool_names:
                target_tool = tool_names[0]
                target_tool_schema = tools[0].get("inputSchema", {})

            if not target_tool:
                return FabricResult(success=False, error=f"No usable tools found. Available: {tool_names}")

            # Determine the correct argument name from the tool's input schema
            schema_props = target_tool_schema.get("properties", {})
            if "userQuestion" in schema_props:
                tool_arguments = {"userQuestion": question}
            elif "query" in schema_props:
                tool_arguments = {"query": question}
            else:
                # Default: use the first required field or "question"
                required = target_tool_schema.get("required", [])
                arg_name = required[0] if required else "question"
                tool_arguments = {arg_name: question}

            logger.info(f"Fabric MCP calling tool '{target_tool}' with args: {tool_arguments}")

            call_resp = await client.post(
                mcp_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": target_tool,
                        "arguments": tool_arguments,
                    },
                },
                headers=session_headers,
            )
            import json as _json
            response_json = call_resp.json()
            logger.info(
                f"Fabric MCP tools/call: status={call_resp.status_code}\n"
                f"Response JSON:\n{_json.dumps(call_resp.json(), indent=2, default=str)}"
            )

            if call_resp.status_code >= 400:
                return FabricResult(
                    success=False,
                    error=f"Fabric tool call failed ({call_resp.status_code}): {call_resp.text[:500]}",
                )

            call_data = response_json
            result_content = call_data.get("result", {}).get("content", [])
            tool_reported_error = call_data.get("result", {}).get("isError", False)

            summary = ""
            data = {}
            for item in result_content:
                if item.get("type") == "text":
                    summary += item.get("text", "")
                elif item.get("type") == "resource":
                    data = item.get("resource", {})

            if tool_reported_error or _looks_like_auth_error(summary):
                logger.error(
                    "Fabric tool returned an authorization or tool error: %s",
                    summary[:1000],
                )
                return FabricResult(
                    success=False,
                    error=summary or str(call_data),
                    data=data,
                    summary=summary,
                )

            return FabricResult(
                success=True,
                data=data or {"raw_response": summary},
                summary=summary or str(call_data),
            )

    except BaseException as e:
        # MCP client wraps errors in ExceptionGroup/TaskGroup — unwrap
        root_cause = e
        if hasattr(e, "exceptions"):
            root_cause = e.exceptions[0] if e.exceptions else e
        # Log response body if available (for HTTP errors)
        detail = str(root_cause)
        if hasattr(root_cause, "response"):
            try:
                detail += f" | Body: {root_cause.response.text}"
            except Exception:
                pass
        logger.error(f"Fabric agent error: {detail}", exc_info=root_cause)
        return FabricResult(success=False, error=detail)


def _looks_like_auth_error(text: str) -> bool:
    """Detect auth-style denial text returned as a normal MCP message."""
    text_lower = text.lower()
    return any(hint in text_lower for hint in _AUTH_ERROR_HINTS)
