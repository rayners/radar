"""Tool for managing document collections."""

from radar.tools import tool


@tool(
    name="manage_documents",
    description=(
        "Manage document collections for indexing and search. "
        "Create, list, delete collections, or trigger re-indexing."
    ),
    parameters={
        "action": {
            "type": "string",
            "description": 'Action: "create", "list", "delete", "index", or "status"',
        },
        "name": {
            "type": "string",
            "description": "Collection name (required for create, delete, index)",
        },
        "base_path": {
            "type": "string",
            "description": 'Base directory path (required for create, e.g. "~/Documents/notes")',
        },
        "patterns": {
            "type": "string",
            "description": 'Comma-separated glob patterns (default: "*.md")',
        },
        "description": {
            "type": "string",
            "description": "Human-readable description for the collection",
        },
    },
)
def manage_documents(
    action: str,
    name: str = "",
    base_path: str = "",
    patterns: str = "*.md",
    description: str = "",
) -> str:
    """Manage document collections."""
    try:
        from radar.config import get_config

        config = get_config()
        if not config.documents.enabled:
            return "Document indexing is disabled in configuration."

        from radar.documents import (
            create_collection,
            delete_collection,
            index_collection,
            list_collections,
        )

        if action == "list":
            collections = list_collections()
            if not collections:
                return "No document collections configured."

            lines = ["Document Collections:\n"]
            for c in collections:
                status = f"Last indexed: {c['last_indexed'] or 'never'}"
                lines.append(
                    f"- **{c['name']}**: {c['base_path']} "
                    f"({c['patterns']}) — {c['file_count']} files, "
                    f"{c['chunk_count']} chunks. {status}"
                )
            return "\n".join(lines)

        if action == "create":
            if not name:
                return "Error: 'name' is required for create."
            if not base_path:
                return "Error: 'base_path' is required for create."

            try:
                coll_id = create_collection(name, base_path, patterns, description)
                return f"Collection '{name}' created (ID: {coll_id}). Run manage_documents(action='index', name='{name}') to index files."
            except Exception as e:
                return f"Error creating collection: {e}"

        if action == "delete":
            if not name:
                return "Error: 'name' is required for delete."
            if delete_collection(name):
                return f"Collection '{name}' and all indexed data deleted."
            return f"Collection '{name}' not found."

        if action == "index":
            if not name:
                return "Error: 'name' is required for index."
            try:
                result = index_collection(name)
                return (
                    f"Indexed collection '{name}': "
                    f"{result['files_indexed']} files indexed, "
                    f"{result['files_skipped']} unchanged, "
                    f"{result['chunks_created']} chunks created, "
                    f"{result['files_removed']} stale files removed."
                )
            except ValueError as e:
                return f"Error: {e}"

        if action == "status":
            collections = list_collections()
            if not collections:
                return "No document collections configured."

            total_files = sum(c["file_count"] for c in collections)
            total_chunks = sum(c["chunk_count"] for c in collections)
            return (
                f"Document indexing: {len(collections)} collections, "
                f"{total_files} files, {total_chunks} chunks total."
            )

        return f"Unknown action: '{action}'. Use 'create', 'list', 'delete', 'index', or 'status'."

    except Exception as e:
        return f"Error managing documents: {e}"
