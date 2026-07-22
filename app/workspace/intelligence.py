"""Workspace Intelligence (Objective 12) — the AI summary + suggested next
actions, generated via the existing LLM provider and cached in
workspace_summaries so dashboards open instantly. Suggestions combine
deterministic rules (always available) with the model's summary."""
from __future__ import annotations

from loguru import logger

from app.document_platform.conversation.llm import get_llm_provider
from app.document_platform.conversation.prompts import StructuredPrompt
from app.workspace.repository import WorkspaceRepository


def rule_based_suggestions(stats: dict[str, int]) -> list[str]:
    suggestions: list[str] = []
    if stats.get("documents", 0) == 0:
        suggestions.append("Upload your first document to build the knowledge base")
    elif stats.get("conversations", 0) == 0:
        suggestions.append("Start a conversation to ask questions about your documents")
    if stats.get("documents", 0) >= 2:
        suggestions.append("Compare documents in a multi-document conversation")
    if stats.get("conversations", 0) >= 1 and stats.get("artifacts", 0) == 0:
        suggestions.append("Generate an executive summary PDF from your knowledge")
    if stats.get("conversations", 0) >= 3:
        suggestions.append("Save an important conversation as searchable knowledge")
    return suggestions[:3] or ["Ask a question about your documents"]


class WorkspaceIntelligence:
    def __init__(self, repo: WorkspaceRepository) -> None:
        self._repo = repo

    async def refresh_summary(self, workspace_id: str, workspace_name: str) -> dict:
        stats = await self._repo.stats(workspace_id)
        recent_titles = await self._repo.recent_conversation_titles(workspace_id)
        docs = await self._repo.documents_for(workspace_id)
        doc_names = [d.original_filename for d in docs[:8]]
        suggestions = rule_based_suggestions(stats)

        summary_text = ""
        model_name = ""
        if stats["documents"] or stats["conversations"]:
            try:
                provider = get_llm_provider()
                model_name = provider.model_name
                prompt = StructuredPrompt(
                    system=(
                        "You summarize a project workspace in 2-3 sentences. Be "
                        "concrete and useful. Reply with ONLY the summary prose."
                    ),
                    user=(
                        f"Workspace: {workspace_name}\n"
                        f"Documents ({stats['documents']}): {', '.join(doc_names) or 'none'}\n"
                        f"Conversations ({stats['conversations']}), recent topics: "
                        f"{', '.join(recent_titles) or 'none'}\n"
                        f"Generated artifacts: {stats['artifacts']}"
                    ),
                    strategy="workspace_summary",
                )
                result = await provider.generate(prompt)
                summary_text = result.text.strip()[:2000]
            except Exception as e:
                logger.warning(f"Workspace summary generation failed: {e}")

        await self._repo.upsert_summary(
            workspace_id, summary_text, stats, suggestions, model_name,
        )
        return {
            "summary": summary_text, "stats": stats,
            "suggestions": suggestions, "model": model_name,
        }
