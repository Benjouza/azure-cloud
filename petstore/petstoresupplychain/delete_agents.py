"""
Utility script to list and force-delete agents (and all their versions) from Azure AI Foundry,
and to bulk-delete sessions (conversations) by ID.

Usage:
    # List all agents and their real version IDs (dry run, no deletion)
    python delete_agents.py

    # Force-delete a specific agent and ALL its versions
    python delete_agents.py --name petstoresupplychain-orchestrator-agent

    # Force-delete ALL agents in the project
    python delete_agents.py --all

    # Delete one or more sessions by ID (space-separated)
    python delete_agents.py --kill-sessions <id1> <id2> ...

    # Delete all 6 known idle sessions (pre-populated from portal screenshot)
    python delete_agents.py --kill-known-sessions

Note: The Azure AI SDK has no "list all sessions" API. Session IDs are visible
in the Foundry portal under Traces > Sessions, or printed by the app on startup.
"""

import argparse
import sys
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from src.config import settings

load_dotenv(".env")


def get_client() -> AIProjectClient:
    return AIProjectClient(
        endpoint=settings.project_endpoint,
        credential=DefaultAzureCredential(),
    )


def list_agents(client: AIProjectClient) -> list:
    agents = list(client.agents.list())
    if not agents:
        print("No agents found.")
        return agents
    print(f"{'NAME':<45} {'KIND':<12} {'VERSION IDs'}")
    print("-" * 80)
    for a in agents:
        versions = list(client.agents.list_versions(a.name))
        # Show the raw .version strings the API returns so the user can see their real format
        version_ids = ", ".join(repr(v.version) for v in versions) if versions else "(none)"
        kind = getattr(a, 'kind', 'unknown')
        print(f"{a.name:<45} {str(kind):<12} {version_ids}")
    return agents


def force_delete_agent(client: AIProjectClient, agent_name: str):
    """Delete all versions of an agent then the agent itself."""
    versions = list(client.agents.list_versions(agent_name))
    if not versions:
        print(f"  (no versions found for '{agent_name}')")
    for v in versions:
        ver_id = v.version  # use the exact ID returned by the API
        print(f"  Deleting version {ver_id!r} of '{agent_name}'...")
        client.agents.delete_version(agent_name=agent_name, agent_version=ver_id)
        print(f"  ✓ Version {ver_id!r} deleted.")
    print(f"Deleting agent '{agent_name}'...")
    client.agents.delete(agent_name=agent_name)
    print(f"✓ Agent '{agent_name}' deleted.")


def force_delete_conversation(client: AIProjectClient, conversation_id: str):
    """Delete a specific conversation/session by ID."""
    openai_client = client.get_openai_client()
    print(f"Deleting conversation '{conversation_id}'...")
    result = openai_client.conversations.delete(conversation_id)
    print(f"✓ Deleted: {result}")


# Session IDs visible in the Foundry portal (Traces > Sessions) as of 2026-05-28
KNOWN_IDLE_SESSIONS = [
    "6d17f0789397404e00rZWygX5aybc274PC2s6JASRzYg80L0eY",
    "f4d79a036a79e45500jhO60gGiq7SSL7wBtUq6bbzA28Ufjc2x",
    "17aeb0b82253266900kYAjBmLhaxvfpVsJbFrnxFQVSA3FbdUy",
    "b5f83593a8557dbf00aateSVDGLtBkUO2kpe1CZjVMTyG2RElE",
    "2d4b2ff56837b82b00iiS1Cun0p962xSkz9lOSql3VDfEoSh9Y",
    "bd394d3740596cf100GMtqty7WERiKMQk3D4H5jNYbL1SUKVjR",
]


def main():
    parser = argparse.ArgumentParser(description="Force-delete Azure AI Foundry agents and sessions.")
    parser.add_argument("--name", help="Agent name to delete.")
    parser.add_argument("--all", action="store_true", help="Delete ALL agents in the project.")
    parser.add_argument("--kill-sessions", nargs="+", metavar="SESSION_ID",
                        help="Delete one or more sessions by ID.")
    parser.add_argument("--kill-known-sessions", action="store_true",
                        help="Delete all known idle sessions from the portal (pre-populated list).")
    args = parser.parse_args()

    client = get_client()

    if args.kill_known_sessions:
        print(f"Deleting {len(KNOWN_IDLE_SESSIONS)} known idle session(s)...")
        for sid in KNOWN_IDLE_SESSIONS:
            try:
                force_delete_conversation(client, sid)
            except Exception as e:
                print(f"  ✗ Failed to delete {sid!r}: {e}")
        sys.exit(0)

    if args.kill_sessions:
        for sid in args.kill_sessions:
            try:
                force_delete_conversation(client, sid)
            except Exception as e:
                print(f"  ✗ Failed to delete {sid!r}: {e}")
        sys.exit(0)

    if not args.name and not args.all:
        print("=== Agents in project (dry run — no changes made) ===")
        list_agents(client)
        print("\nTo delete: --name <agent_name>  or  --all")
        sys.exit(0)

    if args.all:
        agents = list(client.agents.list())
        if not agents:
            print("No agents to delete.")
            sys.exit(0)
        print(f"About to force-delete {len(agents)} agent(s):")
        for a in agents:
            print(f"  - {a.name}")
        confirm = input("\nType 'yes' to confirm: ").strip()
        if confirm.lower() != "yes":
            print("Aborted.")
            sys.exit(0)
        for a in agents:
            force_delete_agent(client, a.name)
    else:
        force_delete_agent(client, args.name)

    print("\nDone.")


if __name__ == "__main__":
    main()
