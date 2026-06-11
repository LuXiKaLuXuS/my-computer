from __future__ import annotations

from pathlib import Path

from app.config import get_settings

settings = get_settings()

ALLOWED_EXTENSIONS = {".py", ".md", ".yml", ".yaml", ".ini", ".toml", ".txt", ".html"}
BLOCKED_DIRS = {".venv", ".git", "__pycache__", ".data", "node_modules"}


class ReadOnlySourceReader:
    """Read-only access to project source code (sandboxed)."""

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.meta_agent_source_root).resolve()

    def _safe_path(self, relative: str) -> Path:
        target = (self.root / relative).resolve()
        if not str(target).startswith(str(self.root)):
            raise PermissionError("Path traversal blocked")
        return target

    def list_files(self, subdir: str = "app", limit: int = 200) -> list[str]:
        base = self._safe_path(subdir)
        if not base.exists():
            return []
        files: list[str] = []
        for path in base.rglob("*"):
            if any(part in BLOCKED_DIRS for part in path.parts):
                continue
            if path.is_file() and path.suffix in ALLOWED_EXTENSIONS:
                files.append(str(path.relative_to(self.root)))
            if len(files) >= limit:
                break
        return sorted(files)

    def read_file(self, relative_path: str, max_chars: int = 50000) -> str:
        path = self._safe_path(relative_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(relative_path)
        if path.suffix not in ALLOWED_EXTENSIONS:
            raise PermissionError(f"Extension not allowed: {path.suffix}")
        content = path.read_text(encoding="utf-8", errors="replace")
        return content[:max_chars]

    def summarize_structure(self) -> dict:
        return {
            "root": str(self.root),
            "app_files": self.list_files("app", limit=100),
            "top_level": [p.name for p in self.root.iterdir() if p.is_file()],
        }