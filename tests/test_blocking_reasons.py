import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import delete

from src.modules.blocking_reasons.models import BlockingReason
from src.modules.tickets.models import Ticket

@pytest.mark.asyncio
async def test_list_returns_active_reasons(client: AsyncClient, moderator_headers: dict):
    # Happy path: GET /api/v1/blocking-reasons (defaults to active=True)
    response = await client.get("/api/v1/blocking-reasons", headers=moderator_headers)
    assert response.status_code == 200
    data = response.json()

    # Должно вернуться ровно 10 активных предустановленных причин
    assert len(data) == 10
    for item in data:
        assert "id" in item
        assert "code" in item
        assert "title" in item
        assert "hard_block" in item
        assert item["is_active"] is True

    # Проверяем фильтрацию по hard_block=true
    response_hard = await client.get("/api/v1/blocking-reasons?hard_block=true", headers=moderator_headers)
    assert response_hard.status_code == 200
    data_hard = response_hard.json()
    assert len(data_hard) == 3
    for item in data_hard:
        assert item["hard_block"] is True

    # Проверяем фильтрацию по hard_block=false
    response_soft = await client.get("/api/v1/blocking-reasons?hard_block=false", headers=moderator_headers)
    assert response_soft.status_code == 200
    data_soft = response_soft.json()
    assert len(data_soft) == 7
    for item in data_soft:
        assert item["hard_block"] is False

@pytest.mark.asyncio
async def test_inactive_reasons_not_visible(client: AsyncClient, test_db: AsyncSession, moderator_headers: dict):
    # Создаем деактивированную (is_active=False) причину в БД
    inactive_reason = BlockingReason(
        id=uuid.uuid4(),
        code="TEST_INACTIVE",
        title="Тестовая деактивированная причина",
        hard_block=False,
        is_active=False
    )
    test_db.add(inactive_reason)
    await test_db.commit()

    # GET /api/v1/blocking-reasons по умолчанию возвращает только активные (is_active=True)
    response = await client.get("/api/v1/blocking-reasons", headers=moderator_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 10
    assert not any(item["code"] == "TEST_INACTIVE" for item in data)

    # GET /api/v1/blocking-reasons?is_active=false возвращает неактивные причины
    response_inactive = await client.get("/api/v1/blocking-reasons?is_active=false", headers=moderator_headers)
    assert response_inactive.status_code == 200
    data_inactive = response_inactive.json()
    assert any(item["code"] == "TEST_INACTIVE" for item in data_inactive)

@pytest.mark.asyncio
async def test_referenced_reason_cannot_be_deleted(client: AsyncClient, test_db: AsyncSession, admin_headers: dict):
    # 1. Создаем причину блокировки
    reason_id = uuid.uuid4()
    reason = BlockingReason(
        id=reason_id,
        code="TEST_REFERENCED",
        title="Тестовая используемая причина",
        hard_block=False,
        is_active=True
    )
    test_db.add(reason)
    await test_db.commit()

    # 2. Создаем карточку модерации (тикет), ссылающийся на эту причину
    ticket_id = uuid.uuid4()
    ticket = Ticket(
        id=ticket_id,
        product_id=uuid.uuid4(),
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="BLOCKED"
    )
    ticket.blocking_reasons.append(reason)
    test_db.add(ticket)
    await test_db.commit()

    # 3. Проверяем запрет физического удаления из БД (должно выбросить IntegrityError из-за ON DELETE RESTRICT)
    with pytest.raises(IntegrityError):
        await test_db.execute(delete(BlockingReason).where(BlockingReason.id == reason_id))

    # Откатываем транзакцию после ошибки БД, чтобы вернуть сессию в рабочее состояние
    await test_db.rollback()

    # 4. Проверяем API-удаление (DELETE эндпоинт производит мягкую деактивацию)
    response = await client.delete(f"/api/v1/blocking-reasons/{reason_id}", headers=admin_headers)
    assert response.status_code == 204

    # Проверяем, что запись осталась в БД, но теперь имеет статус is_active = False
    refreshed_reason = await test_db.get(BlockingReason, reason_id)
    assert refreshed_reason is not None
    assert refreshed_reason.is_active is False

    # Карточка модерации осталась нетронутой и продолжает ссылаться на причину
    refreshed_ticket = await test_db.get(Ticket, ticket_id)
    assert refreshed_ticket is not None
    assert refreshed_ticket.status == "BLOCKED"

@pytest.mark.asyncio
async def test_endpoints_authorization(client: AsyncClient, moderator_headers: dict, admin_headers: dict):
    # Тест на отсутствие заголовка Authorization
    response = await client.get("/api/v1/blocking-reasons")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"

    # POST запрос создания
    payload = {
        "code": "NEW_REASON",
        "title": "Новая причина",
        "hard_block": False
    }

    # 1. POST без токена -> 401
    response = await client.post("/api/v1/blocking-reasons", json=payload)
    assert response.status_code == 401

    # 2. POST под MODERATOR -> 403 Forbidden
    response = await client.post("/api/v1/blocking-reasons", json=payload, headers=moderator_headers)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"

    # 3. POST под ADMIN -> 201 Created
    response = await client.post("/api/v1/blocking-reasons", json=payload, headers=admin_headers)
    assert response.status_code == 201
    reason_id = response.json()["id"]

    # PATCH запрос обновления
    patch_payload = {"title": "Обновленное название"}

    # 1. PATCH без токена -> 401
    response = await client.patch(f"/api/v1/blocking-reasons/{reason_id}", json=patch_payload)
    assert response.status_code == 401

    # 2. PATCH под MODERATOR -> 403 Forbidden
    response = await client.patch(f"/api/v1/blocking-reasons/{reason_id}", json=patch_payload, headers=moderator_headers)
    assert response.status_code == 403

    # 3. PATCH под ADMIN -> 200 OK
    response = await client.patch(f"/api/v1/blocking-reasons/{reason_id}", json=patch_payload, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["title"] == "Обновленное название"

    # DELETE запрос деактивации
    # 1. DELETE без токена -> 401
    response = await client.delete(f"/api/v1/blocking-reasons/{reason_id}")
    assert response.status_code == 401

    # 2. DELETE под MODERATOR -> 403 Forbidden
    response = await client.delete(f"/api/v1/blocking-reasons/{reason_id}", headers=moderator_headers)
    assert response.status_code == 403

    # 3. DELETE под ADMIN -> 204 No Content
    response = await client.delete(f"/api/v1/blocking-reasons/{reason_id}", headers=admin_headers)
    assert response.status_code == 204
