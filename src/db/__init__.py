from src.db.base import Base
from src.modules.blocking_reasons.models import BlockingReason
from src.modules.tickets.models import Ticket, ticket_blocking_reasons
from src.modules.b2b_events.models import EventIdempotencyKey



# Импортируйте все будущие модели сюда, чтобы метаданные Base загрузились для Alembic
# Иначе alembic --autogenerate не сможет найти таблицы

