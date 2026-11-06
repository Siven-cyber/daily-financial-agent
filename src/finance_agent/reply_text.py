"""Conservative Telegram plain-text chunks measured in UTF-16 units."""


def split_text(text: str, limit: int = 4000) -> list[str]:
    if limit < 2:
        raise ValueError('Chunk limit must accommodate supplementary characters')
    parts = []
    start = 0
    units = 0
    for index, char in enumerate(text):
        width = 2 if ord(char) > 0xffff else 1
        if units + width > limit:
            parts.append(text[start:index])
            start = index
            units = 0
        units += width
    parts.append(text[start:])
    return parts
