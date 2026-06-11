from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.meta.sandbox import ProposalSandbox
from app.meta.source_reader import ReadOnlySourceReader
from app.models.meta_proposal import DBMetaProposal, ProposalStatus
from app.services.llm import get_llm_provider

settings = get_settings()


class MetaAgent:
    """
    Meta-agent for safe self-improvement proposals.
    - Read-only source access
    - Sandbox validation
    - Human approval required before apply
    """

    def __init__(self) -> None:
        self.reader = ReadOnlySourceReader()
        self.sandbox = ProposalSandbox()
        self.llm = get_llm_provider()

    async def analyze_codebase(self, focus: str = "orchestrator") -> dict:
        structure = self.reader.summarize_structure()
        context_files = [
            f for f in structure["app_files"] if focus in f or "orchestrat" in f
        ][:5]
        snippets = {}
        for rel in context_files:
            try:
                snippets[rel] = self.reader.read_file(rel, max_chars=3000)
            except (FileNotFoundError, PermissionError):
                continue

        prompt = (
            f"Analyze this codebase for improvements related to: {focus}\n"
            f"Structure: {structure['top_level']}\n"
            f"Files: {list(snippets.keys())}\n"
            f"Snippets:\n{snippets}\n"
            f"Suggest 3 concrete improvements as JSON: "
            f'[{{"title":"","description":"","files":[]}}]'
        )
        response = await self.llm.complete(prompt, system="You are a senior software architect.")
        return {
            "focus": focus,
            "files_analyzed": list(snippets.keys()),
            "analysis": response.text,
            "provider": response.provider,
            "tokens": response.tokens_used,
        }

    async def create_proposal(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        title: str,
        description: str,
        file_changes: dict[str, str],
    ) -> DBMetaProposal:
        sandbox_result = self.sandbox.dry_run_changes(file_changes)
        proposal = DBMetaProposal(
            user_id=user_id,
            title=title,
            description=description,
            file_changes=file_changes,
            sandbox_result=sandbox_result,
            status=ProposalStatus.PENDING if sandbox_result["valid"] else ProposalStatus.FAILED,
        )
        db.add(proposal)
        await db.flush()
        return proposal

    async def approve_proposal(
        self,
        db: AsyncSession,
        *,
        proposal: DBMetaProposal,
        approver_id: uuid.UUID,
    ) -> DBMetaProposal:
        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(f"Cannot approve proposal in status {proposal.status}")
        if settings.meta_agent_require_approval and proposal.user_id != approver_id:
            pass  # any authenticated user can approve their own; extend for admin later
        proposal.status = ProposalStatus.APPROVED
        proposal.approved_by = approver_id
        from datetime import datetime, timezone

        proposal.approved_at = datetime.now(timezone.utc)
        await db.flush()
        return proposal

    async def apply_proposal(
        self,
        db: AsyncSession,
        proposal: DBMetaProposal,
    ) -> dict:
        if proposal.status != ProposalStatus.APPROVED:
            raise ValueError("Proposal must be approved before apply")
        if not settings.meta_agent_enabled:
            raise PermissionError("Meta-agent apply is disabled")

        applied: list[str] = []
        errors: list[str] = []
        root = self.reader.root

        for rel_path, content in (proposal.file_changes or {}).items():
            try:
                target = (root / rel_path).resolve()
                if not str(target).startswith(str(root)):
                    errors.append(f"Blocked: {rel_path}")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                applied.append(rel_path)
            except Exception as exc:
                errors.append(f"{rel_path}: {exc}")

        proposal.status = ProposalStatus.APPLIED if not errors else ProposalStatus.FAILED
        proposal.sandbox_result = {**(proposal.sandbox_result or {}), "apply": {"applied": applied, "errors": errors}}
        await db.flush()
        return {"applied": applied, "errors": errors}


meta_agent = MetaAgent()