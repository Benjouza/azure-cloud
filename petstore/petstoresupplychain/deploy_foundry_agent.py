"""Deploy the PetStore Supply Chain Orchestrator as a Hosted (Code) Agent in Foundry.

Supports two deployment methods:
  1. Source code deploy (default) — zips and uploads your code to Foundry
  2. Container deploy — pushes a Docker image to ACR and registers it

Usage:
    python deploy_foundry_agent.py                    # source code deploy
    python deploy_foundry_agent.py --method container # container deploy
    python deploy_foundry_agent.py --prune-old-versions --keep 3
"""

import argparse
import os
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

load_dotenv(".env.generated")
load_dotenv(".env", override=True)

from src.config import settings

PROJECT_ROOT = Path(__file__).parent
AGENT_NAME = settings.agent_name


def deploy_source():
    """Deploy agent by uploading source code to Foundry."""
    from azure.ai.projects.models import (
        HostedAgentDefinition,
        CodeConfiguration,
        ProtocolVersionRecord,
        AgentProtocol,
    )

    credential = DefaultAzureCredential()
    client = AIProjectClient(
        endpoint=settings.project_endpoint,
        credential=credential,
        allow_preview=True,
    )

    # Create a zip of the source code
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "agent-source"
        # Include only what's needed for the agent runtime
        include_patterns = [
            "startup.py",
            "main.py",
            "requirements.txt",
        ]

        source_dir = Path(tmpdir) / "source"
        source_dir.mkdir()

        for pattern in include_patterns:
            src = PROJECT_ROOT / pattern
            dst = source_dir / pattern
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            elif src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        archive = shutil.make_archive(str(zip_path), "zip", str(source_dir))
        print(f"📦 Source archive: {archive} ({os.path.getsize(archive)} bytes)")

        definition = HostedAgentDefinition(
            cpu="1",
            memory="2Gi",
            code_configuration=CodeConfiguration(
                runtime="python_3_13",
                entry_point=["python", "startup.py"],
            ),
            protocol_versions=[
                ProtocolVersionRecord(protocol=AgentProtocol.INVOCATIONS, version="1.0.0"),
            ],
            environment_variables={
                "AZURE_AI_PROJECT_ENDPOINT": settings.project_endpoint,
                "MODEL_DEPLOYMENT_NAME": settings.model_deployment,
                "APPINSIGHTS_CONNECTION_STRING": settings.appinsights_connection_string,
                "PYTHONUNBUFFERED": "1",
            },
        )

        # The API requires multipart/form-data when code_configuration is present.
        # The SDK's create_version doesn't support this yet, so we send the request manually.
        import json as _json
        import hashlib
        from azure.core.rest import HttpRequest
        from azure.ai.projects._utils.model_base import SdkJSONEncoder

        AGENT_DESCRIPTION = (
            "PetStore Supply Chain Orchestrator Agent. "
            "Routes queries to: (1) Microsoft Fabric Data Agent for supply-chain data "
            "(inventory, orders, suppliers, shipments) and (2) Azure AI Search (Foundry IQ) "
            "for policy/knowledge retrieval (returns, compliance, SOPs). "
            "Classifies user intent and delegates to the appropriate tool automatically."
        )

        body_json = _json.dumps(
            {"definition": definition, "description": AGENT_DESCRIPTION},
            cls=SdkJSONEncoder,
            exclude_readonly=True,
        )
        # Inject dependency_resolution into code_configuration (not yet in SDK model)
        body_dict = _json.loads(body_json)
        body_dict["definition"]["code_configuration"]["dependency_resolution"] = "requirements_txt"
        body_json = _json.dumps(body_dict)

        # Compute SHA-256 of the zip file
        with open(archive, "rb") as f:
            zip_sha256 = hashlib.sha256(f.read()).hexdigest()

        with open(archive, "rb") as zip_file:
            files = [
                ("metadata", (None, body_json, "application/json")),
                ("code", ("agent-source.zip", zip_file, "application/zip")),
            ]
            request = HttpRequest(
                method="POST",
                url=f"{settings.project_endpoint}/agents/{AGENT_NAME}/versions",
                params={"api-version": "v1"},
                files=files,
                headers={
                    "Foundry-Features": "HostedAgents=V1Preview, CodeAgents=V1Preview",
                    "x-ms-code-zip-sha256": zip_sha256,
                },
            )
            response = client._client._pipeline.run(request)  # pylint: disable=protected-access

        if response.http_response.status_code != 200:
            body_text = response.http_response.text()
            raise RuntimeError(
                f"Deploy failed ({response.http_response.status_code}): {body_text}"
            )

        result = response.http_response.json()
        version_id = result.get("version", result.get("id", "unknown"))

    print(f"\n✅ Hosted agent deployed!")
    print(f"   Agent name : {AGENT_NAME}")
    print(f"   Version    : {version_id}")
    return result


def deploy_container():
    """Deploy agent using a pre-built container image."""
    from azure.ai.projects.models import (
        HostedAgentDefinition,
        ProtocolVersionRecord,
        AgentProtocol,
    )

    acr_server = os.environ.get("ACR_LOGIN_SERVER", "")
    image = os.environ.get("AGENT_IMAGE", f"{acr_server}/petstoresupplychain-orchestrator:latest")

    if not acr_server and not os.environ.get("AGENT_IMAGE"):
        print("❌ Set ACR_LOGIN_SERVER or AGENT_IMAGE env var for container deploy")
        print("   Run: source .env.generated")
        raise SystemExit(1)

    print(f"🐳 Deploying container image: {image}")

    # Build and push
    print("   Building Docker image...")
    os.system(f"docker build -t {image} .")
    print("   Pushing to ACR...")
    os.system(f"docker push {image}")

    credential = DefaultAzureCredential()
    client = AIProjectClient(
        endpoint=settings.project_endpoint,
        credential=credential,
        allow_preview=True,
    )

    definition = HostedAgentDefinition(
        image=image,
        cpu="1",
        memory="2Gi",
        container_protocol_versions=[
            ProtocolVersionRecord(protocol=AgentProtocol.INVOCATIONS, version="2025-05-01"),
        ],
        environment_variables={
            "AZURE_AI_PROJECT_ENDPOINT": settings.project_endpoint,
            "MODEL_DEPLOYMENT_NAME": settings.model_deployment,
        },
    )

    agent_version = client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=definition,
    )

    print(f"\n✅ Hosted container agent deployed!")
    print(f"   Agent name : {AGENT_NAME}")
    print(f"   Version    : {agent_version.version}")
    return agent_version


def prune_old_versions(keep: int):
    credential = DefaultAzureCredential()
    client = AIProjectClient(
        endpoint=settings.project_endpoint,
        credential=credential,
        allow_preview=True,
    )

    versions = list(client.agents.list_versions(AGENT_NAME))
    if len(versions) <= keep:
        print(f"No pruning needed. Existing versions: {len(versions)} (keep={keep})")
        return

    sorted_versions = sorted(
        versions,
        key=lambda v: getattr(v, "created_at", 0),
        reverse=True,
    )
    to_delete = sorted_versions[keep:]

    print(f"Pruning {len(to_delete)} old version(s)...")
    for v in to_delete:
        client.agents.delete_version(agent_name=AGENT_NAME, agent_version=v.version)
        print(f"  ✓ Deleted version {v.version}")


def main():
    parser = argparse.ArgumentParser(description="Deploy hosted agent to Azure AI Foundry")
    parser.add_argument(
        "--method",
        choices=["source", "container"],
        default="source",
        help="Deployment method (default: source)",
    )
    parser.add_argument("--prune-old-versions", action="store_true")
    parser.add_argument("--keep", type=int, default=3)
    args = parser.parse_args()

    print("=" * 60)
    print(" PetStore Supply Chain Orchestrator — Hosted Agent Deploy")
    print(f" Agent  : {AGENT_NAME}")
    print(f" Method : {args.method}")
    print("=" * 60)

    if args.method == "source":
        deploy_source()
    else:
        deploy_container()

    if args.prune_old_versions:
        prune_old_versions(args.keep)


if __name__ == "__main__":
    main()
