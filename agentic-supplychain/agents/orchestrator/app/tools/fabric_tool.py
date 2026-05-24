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
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        credential = DefaultAzureCredential()
        token = credential.get_token("https://api.fabric.microsoft.com/.default")

        headers = {"Authorization": f"Bearer {token.token}"}

        async with sse_client(endpoint, headers=headers) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # List available tools to find the query/chat tool
                tools_result = await session.list_tools()
                tool_names = [t.name for t in tools_result.tools]
                logger.info(f"Fabric MCP tools available: {tool_names}")

                # Call the appropriate tool — Fabric data agents typically expose
                # "query" or "ask" or similar; try common names
                target_tool = None
                for candidate in ["query", "ask", "chat", "execute_query", "run_query"]:
                    if candidate in tool_names:
                        target_tool = candidate
                        break

                if not target_tool and tool_names:
                    # Fall back to first available tool
                    target_tool = tool_names[0]
                    logger.info(f"Using first available tool: {target_tool}")

                if not target_tool:
                    return FabricResult(
                        success=False,
                        error="No tools available on Fabric MCP agent",
                    )

                result = await session.call_tool(
                    target_tool,
                    arguments={"question": question},
                )

                # Extract text content from MCP result
                summary = ""
                data = {}
                for content in result.content:
                    if hasattr(content, "text"):
                        summary += content.text
                    elif hasattr(content, "data"):
                        data = content.data

                return FabricResult(
                    success=True,
                    data=data or {"raw_response": summary},
                    summary=summary or str(data),
                )

    except Exception as e:
        logger.error(f"Fabric agent error: {e}")
        return FabricResult(success=False, error=str(e))
