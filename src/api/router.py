from fastapi import APIRouter
from src.modules.blocking_reasons.router import router as blocking_reasons_router
from src.modules.b2b_events.router import router as b2b_events_router
from src.modules.tickets.router import queue_router, tickets_router

api_router = APIRouter()

# Регистрируйте роутеры модулей здесь:
api_router.include_router(blocking_reasons_router, prefix="/blocking-reasons", tags=["BlockingReasons"])
api_router.include_router(b2b_events_router, prefix="/b2b", tags=["B2B Events"])
api_router.include_router(queue_router, prefix="/queue", tags=["Queue"])
api_router.include_router(tickets_router, prefix="/tickets", tags=["Tickets"])



