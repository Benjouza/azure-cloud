"""Centralized configuration loaded from environment variables."""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv(".env.generated")
load_dotenv(".env", override=True)


@dataclass(frozen=True)
class Settings:
    project_endpoint: str = os.environ.get(
        "AZURE_AI_PROJECT_ENDPOINT",
        os.environ.get("FOUNDRY_PROJECT_ENDPOINT", ""),
    )
    model_deployment: str = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o")
    agent_name: str = os.environ.get(
        "AGENT_NAME",
        os.environ.get("FOUNDRY_AGENT_NAME", "petstoresupplychain-orchestrator-agent"),
    )
    search_endpoint: str = os.environ.get("SEARCH_ENDPOINT", "")
    fabric_data_agent_endpoint: str = os.environ.get("FABRIC_DATA_AGENT_ENDPOINT", "")
    appinsights_connection_string: str = os.environ.get(
        "APPINSIGHTS_CONNECTION_STRING",
        os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", ""),
    )


settings = Settings()
