from __future__ import annotations

import ast
import tempfile
from pathlib import Path
from typing import Any


class ProposalSandbox:
    """Validate proposed code changes without applying them."""

    def validate_python(self, content: str) -> dict[str, Any]:
        errors: list[str] = []
        try:
            ast.parse(content)
        except SyntaxError as exc:
            errors.append(f"SyntaxError: {exc}")
        return {"valid": len(errors) == 0, "errors": errors}

    def dry_run_changes(self, file_changes: dict[str, str]) -> dict[str, Any]:
        results: dict[str, Any] = {"files": {}, "valid": True}
        with tempfile.TemporaryDirectory(prefix="mc-sandbox-") as tmp:
            tmp_path = Path(tmp)
            for rel_path, content in file_changes.items():
                if not rel_path.endswith(".py"):
                    results["files"][rel_path] = {"valid": True, "skipped": "non-python"}
                    continue
                file_result = self.validate_python(content)
                results["files"][rel_path] = file_result
                if not file_result["valid"]:
                    results["valid"] = False
                (tmp_path / rel_path).parent.mkdir(parents=True, exist_ok=True)
                (tmp_path / rel_path).write_text(content, encoding="utf-8")
        return results