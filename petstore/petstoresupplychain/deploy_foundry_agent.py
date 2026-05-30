"""Deploy (publish) a hosted Azure AI Foundry agent version.

Usage:
    python deploy_foundry_agent.py
    python deploy_foundry_agent.py --agent-name petstoresupplychain-orchestrator-agent
    python deploy_foundry_agent.py --prune-old-versions --keep 3
"""

import argparse
from dotenv import load_dotenv
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
)

from src.config import settings
from src.agent import SYSTEM_INSTRUCTIONS


def deploy(agent_name: str) -> str:
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        endpoint=settings.project_endpoint,
        credential=credential,
    )

    fabric_conn = project_client.connections.get(name="petstoresupplychain-fabric-data-agent")
    fabric_tool = MicrosoftFabricPreviewTool(
        fabric_dataagent_preview=FabricDataAgentToolParameters(
            project_connections=[
                ToolProjectConnection(project_connection_id=fabric_conn.id)
            ]
        )
    )

    search_conn = project_client.connections.get_default(ConnectionType.AZURE_AI_SEARCH)
    search_tool = AzureAISearchTool(
        azure_ai_search=AzureAISearchToolResource(
            indexes=[
                {
                    "project_connection_id": search_conn.id,
                    "index_name": "petstoresupplychain-ai-search",
                    "query_type": AzureAISearchQueryType.SEMANTIC,
                    "top_k": 5,
                }
            ]
        )
    )

    version = project_client.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=settings.model_deployment,
            instructions=SYSTEM_INSTRUCTIONS,
            tools=[fabric_tool, search_tool],
        ),
    )

    print("✓ Foundry hosted agent version deployed")
    print(f"  Agent name : {version.name}")
    print(f"  Version    : {version.version}")
    print(f"  ID         : {version.id}")
    return version.version


def prune_old_versions(agent_name: str, keep: int):
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        endpoint=settings.project_endpoint,
        credential=credential,
    )

    versions = list(project_client.agents.list_versions(agent_name))
    if len(versions) <= keep:
        print(f"No pruning needed. Existing versions: {len(versions)} (keep={keep})")
        return

    # Keep newest versions by created_at desc
    sorted_versions = sorted(
        versions,
        key=lambda v: getattr(v, "created_at", 0),
        reverse=True,
    )
    to_delete = sorted_versions[keep:]

    print(f"Pruning {len(to_delete)} old version(s) for '{agent_name}'...")
    for v in to_delete:
        project_client.agents.delete_version(agent_name=agent_name, agent_version=v.version)
        print(f"  ✓ Deleted version {v.version}")


def main():
    load_dotenv(".env")

    parser = argparse.ArgumentParser(description="Deploy hosted Azure AI Foundry agent version")
    parser.add_argument("--agent-name", default=settings.agent_name, help="Agent name")
    parser.add_argument(
        "--prune-old-versions",
        action="store_true",
        help="Delete old versions after deployment",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=3,
        help="How many latest versions to keep when pruning",
    )
    args = parser.parse_args()

    deploy(args.agent_name)

    if args.prune_old_versions:
        prune_old_versions(args.agent_name, args.keep)


if __name__ == "__main__":
    main()
