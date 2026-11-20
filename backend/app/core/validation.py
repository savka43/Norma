def validate_stored_text(value: str) -> str:
    """Reject strings that PostgreSQL text/JSONB cannot store losslessly."""
    if "\x00" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("Text contains unsupported Unicode characters")
    return value
