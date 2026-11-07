"""The labeled plain text that is embedded for each incident."""

_LABELS = (("title", "title"), ("description", "description"), ("resolution", "resolution_summary"))


def embedding_text(title: str, description: str, resolution_summary: str) -> str:
    """Labeled lines in a fixed order; empty fields are left out."""
    values = {"title": title, "description": description, "resolution_summary": resolution_summary}
    lines = [
        f"{label}: {values[field].strip()}" for label, field in _LABELS if values[field].strip()
    ]
    return "\n".join(lines)
