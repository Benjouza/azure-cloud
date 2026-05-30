"""
PetStore Supply Chain Orchestrator Agent

Creates a hosted Foundry agent with two tools:
  1. MicrosoftFabricPreviewTool – routes petstore supply-chain DATA inquiries to the Fabric data agent
  2. AzureAISearchTool – routes POLICY / knowledge inquiries to Azure AI Search

The agent's system prompt classifies incoming user messages by intent and
delegates to the appropriate tool automatically.
"""

import os
import logging
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    PromptAgentDefinition,
    MicrosoftFabricPreviewTool,
    FabricDataAgentToolParameters,
    ToolProjectConnection,
    AzureAISearchTool,
    AzureAISearchToolResource,
    AzureAISearchQueryType,
    ConnectionType,
    MCPTool,
)

from src.config import settings
from src.telemetry import configure_telemetry

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


def create_orchestrator_agent():
    """Provision and return the orchestrator agent, OpenAI client, and project client."""
    tracer = configure_telemetry()

    with tracer.start_as_current_span("create_orchestrator_agent"):
        credential = DefaultAzureCredential()
        project_client = AIProjectClient(
            endpoint=settings.project_endpoint,
            credential=credential,
        )

        # --- Tool 1: Microsoft Fabric Data Agent (petstore supply-chain data queries) ---
        fabric_conn = project_client.connections.get(
            name="petstoresupplychain-fabric-data-agent"
        )
        fabric_tool = MicrosoftFabricPreviewTool(
            fabric_dataagent_preview=FabricDataAgentToolParameters(
                project_connections=[
                    ToolProjectConnection(project_connection_id=fabric_conn.id)
                ]
            )
        )

        # --- Tool 2: Azure AI Search (policy/knowledge retrieval) ---
        search_conn = project_client.connections.get_default(
            ConnectionType.AZURE_AI_SEARCH
        )
        search_tool = AzureAISearchTool(
            azure_ai_search=AzureAISearchToolResource(
                indexes=[{
                    "project_connection_id": search_conn.id,
                    "index_name": "petstoresupplychain-ai-search",
                    "query_type": AzureAISearchQueryType.SEMANTIC,
                    "top_k": 5,
                }]
            )
        )

        # --- Create the orchestrator agent version ---
        agent = project_client.agents.create_version(
            agent_name=settings.agent_name,
            definition=PromptAgentDefinition(
                model=settings.model_deployment,
                instructions=SYSTEM_INSTRUCTIONS,
                tools=[fabric_tool, search_tool],
            ),
        )
        print(f"✓ Agent created – ID: {agent.id}, Name: {agent.name}, Version: {agent.version}")

        # Get an OpenAI-compatible client for conversations
        openai_client = project_client.get_openai_client()

        # Create a conversation thread
        conversation = openai_client.conversations.create()
        print(f"✓ Conversation created – ID: {conversation.id}")

        return project_client, openai_client, agent, conversation


def run_query(openai_client, agent, conversation, user_message: str) -> str:
    """Send a user message to the agent and return the assistant's response."""
    tracer = configure_telemetry()

    with tracer.start_as_current_span("run_query") as span:
        span.set_attribute("user_message", user_message)

        response = openai_client.responses.create(
            input=user_message,
            conversation=conversation.id,
            extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
        )

        # Log tool call results so we can see Fabric/Search failures inline
        for item in getattr(response, 'output', []):
            item_type = getattr(item, 'type', None)
            if item_type == 'tool_call':
                name = getattr(item, 'name', '?')
                status = getattr(item, 'status', '?')
                logging.warning(f"[tool_call] {name} → status={status}")
            elif item_type == 'tool_result':
                tool = getattr(item, 'tool_call_id', '?')
                content = str(getattr(item, 'content', ''))[:300]
                logging.warning(f"[tool_result] {tool}: {content}")

        result = response.output_text
        span.set_attribute("response_length", len(result))
        return result


def cleanup(project_client: AIProjectClient, agent):
    """Delete the agent version."""
    project_client.agents.delete_version(
        agent_name=agent.name,
        agent_version=agent.version,
    )
    print("✓ Agent version deleted.")

