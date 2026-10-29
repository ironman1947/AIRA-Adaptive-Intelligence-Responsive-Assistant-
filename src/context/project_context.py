"""Project Context Manager for AIRA.

Provides isolated project workspaces, project state tracking,
and contextual prompt generation without cross-project contamination.
"""

from typing import List, Optional
from datetime import datetime
from src.memory.models import ProjectWorkspace
from src.memory.repository import MemoryRepository

class ProjectContextManager:
    def __init__(self, repo: MemoryRepository):
        self.repo = repo
        self._ensure_default_project()

    def _ensure_default_project(self):
        projects = self.repo.list_projects()
        if not projects:
            default_proj = ProjectWorkspace(
                id="aira-core",
                name="Project AIRA",
                purpose="Evolve dual-engine agent into AIRA: persistent AI companion, coding coworker, and research assistant.",
                tech_stack=["Python", "FastAPI", "Streamlit", "Ollama", "OpenRouter", "SQLite", "DuckDuckGo"],
                repo_path="/Users/ompradipchougule/hackathon-agent",
                current_objectives=[
                    "Implement AIRA persona and machine-readable runtime state",
                    "Establish persistent memory across restarts",
                    "Build safe internet research and RAG pipelines",
                    "Integrate Robotics-inspired identity constitution and policy layer"
                ],
                completed_milestones=[
                    "Audited existing dual-engine repository and dependencies",
                    "Designed SQLite persistent memory architecture"
                ],
                known_bugs=[],
                open_issues=[],
                architectural_decisions=[
                    "Dual-engine architecture: local Gemma 2B via Ollama and heavy Nemotron 550B via OpenRouter",
                    "SQLite storage with clean repository abstractions for zero extra infra",
                    "Protected operational constitution enforced at the Python execution layer"
                ],
                documentation="Master Engineering Specification for Project AIRA.",
                last_verified_state="In active implementation phase.",
                next_steps=[
                    "Complete Phase 4 & 5 tools and RAG",
                    "Complete Phase 7 & 8 coding tools and constitution",
                    "Enhance Streamlit frontend and run automated tests"
                ]
            )
            self.repo.save_project(default_proj)

    def get_project(self, project_id: str) -> Optional[ProjectWorkspace]:
        return self.repo.get_project(project_id)

    def list_projects(self) -> List[ProjectWorkspace]:
        return self.repo.list_projects()

    def save_project(self, project: ProjectWorkspace) -> ProjectWorkspace:
        project.updated_at = datetime.now().isoformat()
        return self.repo.save_project(project)

    def get_project_prompt_summary(self, project_id: Optional[str] = None) -> Optional[str]:
        if not project_id:
            projects = self.list_projects()
            if not projects:
                return None
            project_id = projects[0].id

        proj = self.get_project(project_id)
        if not proj:
            return None

        lines = [
            f"Project: {proj.name} (ID: {proj.id})",
            f"Purpose: {proj.purpose}",
            f"Tech Stack: {', '.join(proj.tech_stack)}",
        ]
        if proj.current_objectives:
            lines.append("Current Objectives:")
            for obj in proj.current_objectives:
                lines.append(f"  - {obj}")
        if proj.known_bugs:
            lines.append("Known Bugs:")
            for bug in proj.known_bugs:
                lines.append(f"  - {bug}")
        if proj.open_issues:
            lines.append("Open Issues:")
            for issue in proj.open_issues:
                lines.append(f"  - {issue}")
        if proj.next_steps:
            lines.append("Planned Next Steps:")
            for ns in proj.next_steps:
                lines.append(f"  - {ns}")
        if proj.last_verified_state:
            lines.append(f"Last Verified State: {proj.last_verified_state}")

        return "\n".join(lines)
