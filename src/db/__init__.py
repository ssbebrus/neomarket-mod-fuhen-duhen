from src.db.base import Base
from src.modules.blocking_reasons.models import BlockingReason, Ticket, ticket_blocking_reasons


# Импортируйте все будущие модели сюда, чтобы метаданные Base загрузились для Alembic
# Иначе alembic --autogenerate не сможет найти таблицы

