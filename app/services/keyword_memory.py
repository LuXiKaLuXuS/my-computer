import re
from collections import defaultdict


class KeywordMemory:
    """Simple in-process keyword memory per user (v0.8 baseline)."""

    def __init__(self) -> None:
        self._store: dict[str, list[dict]] = defaultdict(list)

    def add(self, user_id: str, content: str, metadata: dict | None = None) -> None:
        keywords = self._extract_keywords(content)
        self._store[user_id].append(
            {"content": content, "keywords": keywords, "metadata": metadata or {}}
        )

    def search(self, user_id: str, query: str, limit: int = 5) -> list[dict]:
        query_keywords = set(self._extract_keywords(query))
        if not query_keywords:
            return self._store[user_id][-limit:]

        scored: list[tuple[float, dict]] = []
        for item in self._store[user_id]:
            item_keywords = set(item["keywords"])
            overlap = len(query_keywords & item_keywords)
            if overlap:
                scored.append((overlap / len(query_keywords), item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
        stop = {"the", "and", "for", "with", "this", "that", "from", "have", "are", "was"}
        return [w for w in words if w not in stop]


keyword_memory = KeywordMemory()