from fastapi import APIRouter
from src.modules.blocking_reasons.router import router as blocking_reasons_router

api_router = APIRouter()

# Регистрируйте роутеры модулей здесь:
api_router.include_router(blocking_reasons_router, prefix="/blocking-reasons", tags=["BlockingReasons"])


