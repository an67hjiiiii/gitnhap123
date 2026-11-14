"""PostgreSQL persistence for authoritative product runtime state."""

from app.storage.postgres.base import Base
from app.storage.postgres import review_models  # noqa: F401 - register review metadata
from app.storage.postgres.config import (
    PostgresConfigurationError,
    create_postgres_engine,
    create_session_factory,
    database_url_from_env,
)
from app.storage.postgres.models import (
    ConversationMessageRecord,
    ConversationRecord,
    KnowledgeChunkRecord,
    KnowledgeSourceRecord,
    RunRecord,
    SessionRecord,
    UserRecord,
)

__all__ = [
    "Base",
    "ConversationMessageRecord",
    "ConversationRecord",
    "KnowledgeChunkRecord",
    "KnowledgeSourceRecord",
    "PostgresConfigurationError",
    "RunRecord",
    "SessionRecord",
    "UserRecord",
    "create_postgres_engine",
    "create_session_factory",
    "database_url_from_env",
]
