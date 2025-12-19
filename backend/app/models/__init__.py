"""SQLAlchemy models.

Importing this package should register all ORM models on `Base.metadata` so Alembic
autogeneration works.
"""

from .base import Base  # noqa: F401

# Import models to register them with SQLAlchemy metadata.
from .api_key import APIKey  # noqa: F401
from .chat import ChatMessage, ChatSession, chat_session_knowledge_bases  # noqa: F401
from .document import Chunk, Document  # noqa: F401
from .knowledge_base import KnowledgeBase  # noqa: F401
from .tenant import Tenant  # noqa: F401
from .user import TenantMembership, User  # noqa: F401
