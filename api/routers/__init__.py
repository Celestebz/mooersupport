from .emails import router as emails_router
from .issues import router as issues_router
from .analysis import router as analysis_router
from .automation import router as automation_router
from .drafts import router as drafts_router
from .logs import router as logs_router
from .prices import router as prices_router
from .templates import router as templates_router
from .knowledge import router as knowledge_router

__all__ = [
    "emails_router", "issues_router", "analysis_router",
    "automation_router", "drafts_router", "logs_router",
    "prices_router", "templates_router", "knowledge_router",
]
