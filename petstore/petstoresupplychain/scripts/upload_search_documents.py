"""Upload knowledge documents from data/knowledge/ to Azure AI Search index."""

import os
import sys
import hashlib
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchFieldDataType,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
)
from dotenv import load_dotenv

load_dotenv(".env.generated")
load_dotenv(".env", override=True)

SEARCH_ENDPOINT = os.environ.get("SEARCH_ENDPOINT", "")
INDEX_NAME = "petstoresupplychain-knowledge"
KNOWLEDGE_DIR = Path(__file__).parent.parent / "data" / "knowledge"

if not SEARCH_ENDPOINT:
    print("ERROR: SEARCH_ENDPOINT not set. Source .env.generated or set it manually.")
    sys.exit(1)


def create_or_update_index(index_client: SearchIndexClient):
    """Create or update the search index with semantic configuration."""
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="category", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="file_path", type=SearchFieldDataType.String),
    ]

    semantic_config = SemanticConfiguration(
        name="default",
        prioritized_fields=SemanticPrioritizedFields(
            title_field=SemanticField(field_name="title"),
            content_fields=[SemanticField(field_name="content")],
        ),
    )

    semantic_search = SemanticSearch(configurations=[semantic_config])

    index = SearchIndex(
        name=INDEX_NAME,
        fields=fields,
        semantic_search=semantic_search,
    )

    index_client.create_or_update_index(index)
    print(f"Index '{INDEX_NAME}' created/updated with semantic configuration.")


def load_documents():
    """Load all markdown files from data/knowledge/ as documents."""
    documents = []

    for md_file in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        relative_path = md_file.relative_to(KNOWLEDGE_DIR)
        category = relative_path.parts[0]  # policies, procedures, contracts
        content = md_file.read_text(encoding="utf-8")
        title = md_file.stem.replace("_", " ").title()
        doc_id = hashlib.md5(str(relative_path).encode()).hexdigest()

        documents.append({
            "id": doc_id,
            "title": title,
            "content": content,
            "category": category,
            "file_path": str(relative_path),
        })

    return documents


def main():
    print(f"Search endpoint: {SEARCH_ENDPOINT}")
    print(f"Index name: {INDEX_NAME}")
    print(f"Knowledge dir: {KNOWLEDGE_DIR}")
    print()

    credential = DefaultAzureCredential()

    # Create index
    index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)
    create_or_update_index(index_client)

    # Load and upload documents
    documents = load_documents()
    print(f"Found {len(documents)} documents to upload:")
    for doc in documents:
        print(f"  - [{doc['category']}] {doc['title']}")

    search_client = SearchClient(
        endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME, credential=credential
    )
    result = search_client.upload_documents(documents=documents)

    succeeded = sum(1 for r in result if r.succeeded)
    failed = sum(1 for r in result if not r.succeeded)

    print(f"\nUpload complete: {succeeded} succeeded, {failed} failed.")
    if failed:
        for r in result:
            if not r.succeeded:
                print(f"  FAILED: {r.key} - {r.error_message}")


if __name__ == "__main__":
    main()
