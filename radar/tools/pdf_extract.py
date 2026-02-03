"""PDF text extraction tool."""

from pathlib import Path

from radar.tools import tool


@tool(
    name="pdf_extract",
    description="Extract text from a PDF file. Can extract from first N pages, last N pages, or all pages.",
    parameters={
        "path": {
            "type": "string",
            "description": "Path to the PDF file",
        },
        "first_pages": {
            "type": "integer",
            "description": "Extract only the first N pages (optional)",
            "optional": True,
        },
        "last_pages": {
            "type": "integer",
            "description": "Extract only the last N pages (optional)",
            "optional": True,
        },
    },
)
def pdf_extract(
    path: str,
    first_pages: int | None = None,
    last_pages: int | None = None,
) -> str:
    """Extract text from PDF file."""
    try:
        import pymupdf
    except ImportError:
        return "Error: pymupdf not installed"

    file_path = Path(path).expanduser().resolve()

    if not file_path.exists():
        return f"Error: File not found: {path}"

    if not file_path.suffix.lower() == ".pdf":
        return f"Error: Not a PDF file: {path}"

    try:
        doc = pymupdf.open(file_path)
    except Exception as e:
        return f"Error opening PDF: {e}"

    try:
        total_pages = len(doc)

        # Determine which pages to extract
        if first_pages is not None and last_pages is not None:
            # Both specified: first N and last N
            first_set = set(range(min(first_pages, total_pages)))
            last_set = set(range(max(0, total_pages - last_pages), total_pages))
            page_indices = sorted(first_set | last_set)
        elif first_pages is not None:
            page_indices = list(range(min(first_pages, total_pages)))
        elif last_pages is not None:
            page_indices = list(range(max(0, total_pages - last_pages), total_pages))
        else:
            page_indices = list(range(total_pages))

        text_parts = []
        for i in page_indices:
            page = doc[i]
            text = page.get_text()
            if text.strip():
                text_parts.append(f"--- Page {i + 1} ---\n{text}")

        doc.close()

        if not text_parts:
            return "No text content found in the specified pages"

        return "\n\n".join(text_parts)

    except Exception as e:
        doc.close()
        return f"Error extracting text: {e}"
