"""
PetStore Supply Chain Orchestrator Agent

Hosted Foundry agent that handles invocations directly using the Azure AI Projects SDK.
Routes queries to:
  1. MicrosoftFabricPreviewTool – petstore supply-chain DATA inquiries via Fabric data agent
  2. AzureAISearchTool – POLICY / knowledge inquiries via Azure AI Search
"""

import logging
import sys
from azure.identity import ManagedIdentityCredential, AzureCliCredential, ChainedTokenCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    MicrosoftFabricPreviewTool,
    FabricDataAgentToolParameters,
    ToolProjectConnection,
    AzureAISearchTool,
    AzureAISearchToolResource,
    AzureAISearchQueryType,
    ConnectionType,
)

from src.config import settings
from src.telemetry import configure_telemetry

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTIONS = """You are the PetStore Supply Chain Orchestrator Agent.

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


def create_orchestrator_client():
    """Create and return the AI Project client with tools configured.

    Returns (project_client, tools).
    """
    logger.info("create_orchestrator_client: starting...")
    configure_telemetry()

    # Use ManagedIdentityCredential in hosted environments, with CLI fallback for local dev
    from azure.identity import ManagedIdentityCredential, AzureCliCredential, ChainedTokenCredential

    credential = ChainedTokenCredential(
        ManagedIdentityCredential(),
        AzureCliCredential(),
    )
    logger.info("Credential chain configured (ManagedIdentity → AzureCLI)")

    project_client = AIProjectClient(
        endpoint=settings.project_endpoint,
        credential=credential,
    )
    logger.info("AIProjectClient created for endpoint: %s", settings.project_endpoint)

    # --- Tool 1: Microsoft Fabric Data Agent (petstore supply-chain data queries) ---
    logger.info("Fetching Fabric connection...")
    fabric_conn = project_client.connections.get(
        name="petstoresupplychain-fabric-data-agent"
    )
    logger.info("Fabric connection ID: %s", fabric_conn.id)
    fabric_tool = MicrosoftFabricPreviewTool(
        fabric_dataagent_preview=FabricDataAgentToolParameters(
            project_connections=[
                ToolProjectConnection(project_connection_id=fabric_conn.id)
            ]
        )
    )

    # --- Tool 2: Azure AI Search (policy/knowledge retrieval) ---
    logger.info("Fetching Azure AI Search connection...")
    search_conn = project_client.connections.get_default(
        ConnectionType.AZURE_AI_SEARCH
    )
    logger.info("Search connection ID: %s", search_conn.id)
    search_tool = AzureAISearchTool(
        azure_ai_search=AzureAISearchToolResource(
            indexes=[{
                "project_connection_id": search_conn.id,
                "index_name": "petstoresupplychain-knowledge",
                "query_type": AzureAISearchQueryType.SEMANTIC,
                "top_k": 5,
            }]
        )
    )

    tools = [fabric_tool, search_tool]
    logger.info("Orchestrator client ready with %d tools", len(tools))
    sys.stdout.flush()
    return project_client, tools


def run_query(project_client: AIProjectClient, tools: list, user_message: str) -> str:
    """Send a user message via the agent service (responses API) and return the response.

    The hosted agent definition already has tools (Fabric, AI Search) configured.
    We use the OpenAI-compatible responses API with agent_reference to delegate
    tool orchestration to the Foundry agent service.
    """
    tracer = configure_telemetry()

    with tracer.start_as_current_span("run_query") as span:
        span.set_attribute("user_message", user_message)
        logger.info("run_query: sending message (%d chars)", len(user_message))

        openai_client = project_client.get_openai_client()
        conversation = openai_client.conversations.create()

        response = openai_client.responses.create(
            input=user_message,
            model=settings.model_deployment,
            extra_body={
                "conversation_id": conversation.id,
                "agent_reference": {
                    "name": settings.agent_name,
                    "type": "agent_reference",
                },
            },
        )

        result = response.output_text
        span.set_attribute("response_length", len(result))
        logger.info("run_query: response received (%d chars)", len(result))
        return result

