import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx
from sqlalchemy import select

from src.config import settings
from src.modules.tickets.models import Ticket
from src.modules.b2b_events.models import EventIdempotencyKey


def make_mock_product(product_id: uuid.UUID, title="Test Product", active_quantity=5, skus_count=1):
    return {
        "id": str(product_id),
        "seller_id": "11111111-1111-1111-1111-111111111111",
        "category_id": "22222222-2222-2222-2222-222222222222",
        "title": title,
        "slug": "test-product",
        "description": "Test description",
        "status": "ON_MODERATION",
        "deleted": False,
        "images": [{"url": "http://img.png", "id": "33333333-3333-3333-3333-333333333333"}],
        "characteristics": [],
        "skus": [
            {
                "product_id": str(product_id),
                "name": f"SKU {i}",
                "price": 100,
                "stock_quantity": active_quantity,
                "active_quantity": active_quantity if i == 0 else 0,
                "id": str(uuid.uuid4()),
                "created_at": "2026-06-09T12:00:00Z",
                "updated_at": "2026-06-09T12:00:00Z"
            }
            for i in range(skus_count)
        ],
        "category": {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "Electronics",
            "level": 1,
            "path": "22222222-2222-2222-2222-222222222222"
        },
        "created_at": "2026-06-09T12:00:00Z",
        "updated_at": "2026-06-09T12:00:00Z"
    }


@pytest.mark.asyncio
async def test_missing_service_header_401(client):
    # Запрос без заголовка
    response = await client.post(
        "/api/v1/b2b/events",
        json={
            "event_type": "PRODUCT_CREATED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-09T12:00:00Z",
            "payload": {
                "product_id": str(uuid.uuid4()),
                "seller_id": str(uuid.uuid4()),
                "json_after": {}
            }
        }
    )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"

    # Запрос с неверным заголовком
    response = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": "wrong-key"},
        json={
            "event_type": "PRODUCT_CREATED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-09T12:00:00Z",
            "payload": {
                "product_id": str(uuid.uuid4()),
                "seller_id": str(uuid.uuid4()),
                "json_after": {}
            }
        }
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_created_pending(client, test_db, monkeypatch):
    product_id = uuid.uuid4()
    seller_id = uuid.uuid4()
    category_id = uuid.uuid4()
    idempotency_key = uuid.uuid4()

    mock_product = make_mock_product(product_id, title="Amazing Product")
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_product
    mock_resp.raise_for_status = MagicMock()

    # Мокаем запрос к B2B
    monkeypatch.setattr(httpx.AsyncClient, "get", AsyncMock(return_value=mock_resp))

    response = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": settings.B2B_TO_MODERATION_KEY},
        json={
            "event_type": "PRODUCT_CREATED",
            "idempotency_key": str(idempotency_key),
            "occurred_at": "2026-06-09T12:00:00Z",
            "payload": {
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "category_id": str(category_id),
                "queue_priority": 3,
                "json_after": {}
            }
        }
    )
    assert response.status_code == 202

    # Проверяем БД
    stmt = select(Ticket).where(Ticket.product_id == product_id)
    result = await test_db.execute(stmt)
    ticket = result.scalar_one_or_none()

    assert ticket is not None
    assert ticket.status == "PENDING"
    assert ticket.kind == "CREATE"
    assert ticket.queue_priority == 3
    assert ticket.json_before is None
    assert ticket.json_after == mock_product

    # Проверяем ключ идемпотентности
    stmt_key = select(EventIdempotencyKey).where(EventIdempotencyKey.key == idempotency_key)
    res_key = await test_db.execute(stmt_key)
    assert res_key.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_edited_returns_to_review(client, test_db, monkeypatch):
    product_id = uuid.uuid4()
    seller_id = uuid.uuid4()

    # Сценарий 1: старый статус BLOCKED -> приоритет 2
    ticket = Ticket(
        product_id=product_id,
        seller_id=seller_id,
        kind="CREATE",
        status="BLOCKED",
        queue_priority=3,
        json_after={"old": "data"}
    )
    test_db.add(ticket)
    await test_db.commit()

    mock_product = make_mock_product(product_id, active_quantity=5)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_product
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr(httpx.AsyncClient, "get", AsyncMock(return_value=mock_resp))

    response = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": settings.B2B_TO_MODERATION_KEY},
        json={
            "event_type": "PRODUCT_EDITED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-09T12:00:00Z",
            "payload": {
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "json_before": {"old": "data"},
                "json_after": {}
            }
        }
    )
    assert response.status_code == 202

    await test_db.refresh(ticket)
    assert ticket.status == "PENDING"
    assert ticket.queue_priority == 2
    assert ticket.json_before == {"old": "data"}
    assert ticket.json_after == mock_product

    # Сценарий 2: старый статус APPROVED, остатки > 0 -> приоритет 3
    ticket.status = "APPROVED"
    ticket.queue_priority = 1
    await test_db.commit()

    response = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": settings.B2B_TO_MODERATION_KEY},
        json={
            "event_type": "PRODUCT_EDITED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-09T12:00:00Z",
            "payload": {
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "json_before": {},
                "json_after": {}
            }
        }
    )
    assert response.status_code == 202

    await test_db.refresh(ticket)
    assert ticket.status == "PENDING"
    assert ticket.queue_priority == 3

    # Сценарий 3: старый статус APPROVED, остатки == 0 -> приоритет 4
    ticket.status = "APPROVED"
    ticket.queue_priority = 1
    await test_db.commit()

    mock_product_no_stock = make_mock_product(product_id, active_quantity=0)
    mock_resp_no_stock = MagicMock(spec=httpx.Response)
    mock_resp_no_stock.status_code = 200
    mock_resp_no_stock.json.return_value = mock_product_no_stock
    mock_resp_no_stock.raise_for_status = MagicMock()

    monkeypatch.setattr(httpx.AsyncClient, "get", AsyncMock(return_value=mock_resp_no_stock))

    response = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": settings.B2B_TO_MODERATION_KEY},
        json={
            "event_type": "PRODUCT_EDITED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-09T12:00:00Z",
            "payload": {
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "json_before": {},
                "json_after": {}
            }
        }
    )
    assert response.status_code == 202

    await test_db.refresh(ticket)
    assert ticket.status == "PENDING"
    assert ticket.queue_priority == 4


@pytest.mark.asyncio
async def test_edited_updates_in_review(client, test_db, monkeypatch):
    product_id = uuid.uuid4()
    seller_id = uuid.uuid4()
    moderator_id = uuid.uuid4()

    # Создаем тикет в процессе модерации
    ticket = Ticket(
        product_id=product_id,
        seller_id=seller_id,
        kind="CREATE",
        status="IN_REVIEW",
        assigned_moderator_id=moderator_id,
        queue_priority=3,
        json_after={"initial": "state"}
    )
    test_db.add(ticket)
    await test_db.commit()

    mock_product = make_mock_product(product_id)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_product
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr(httpx.AsyncClient, "get", AsyncMock(return_value=mock_resp))

    response = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": settings.B2B_TO_MODERATION_KEY},
        json={
            "event_type": "PRODUCT_EDITED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-09T12:00:00Z",
            "payload": {
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "json_before": {"initial": "state"},
                "json_after": {}
            }
        }
    )
    assert response.status_code == 202

    await test_db.refresh(ticket)
    assert ticket.status == "PENDING"
    assert ticket.assigned_moderator_id is None
    assert ticket.json_before == {"initial": "state"}
    assert ticket.json_after == mock_product


@pytest.mark.asyncio
async def test_deleted_archived(client, test_db):
    product_id = uuid.uuid4()
    seller_id = uuid.uuid4()

    # Сеем тикет
    ticket = Ticket(
        product_id=product_id,
        seller_id=seller_id,
        kind="CREATE",
        status="PENDING",
        queue_priority=3
    )
    test_db.add(ticket)
    await test_db.commit()

    # Отправляем DELETE событие
    response = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": settings.B2B_TO_MODERATION_KEY},
        json={
            "event_type": "PRODUCT_DELETED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-09T12:00:00Z",
            "payload": {
                "product_id": str(product_id)
            }
        }
    )
    assert response.status_code == 202

    # Проверяем, что тикет физически удален
    stmt = select(Ticket).where(Ticket.product_id == product_id)
    result = await test_db.execute(stmt)
    assert result.scalar_one_or_none() is None

    # Повторная отправка PRODUCT_DELETED (идемпотентно, ничего не делает, возвращает 202)
    response2 = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": settings.B2B_TO_MODERATION_KEY},
        json={
            "event_type": "PRODUCT_DELETED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-09T12:00:00Z",
            "payload": {
                "product_id": str(product_id)
            }
        }
    )
    assert response2.status_code == 202


@pytest.mark.asyncio
async def test_duplicate_event_no_side_effects(client, test_db, monkeypatch):
    product_id = uuid.uuid4()
    seller_id = uuid.uuid4()
    idempotency_key = uuid.uuid4()

    mock_product = make_mock_product(product_id)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_product
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr(httpx.AsyncClient, "get", AsyncMock(return_value=mock_resp))

    # Первый запрос
    response1 = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": settings.B2B_TO_MODERATION_KEY},
        json={
            "event_type": "PRODUCT_CREATED",
            "idempotency_key": str(idempotency_key),
            "occurred_at": "2026-06-09T12:00:00Z",
            "payload": {
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "json_after": {}
            }
        }
    )
    assert response1.status_code == 202

    # Проверяем, что создался 1 тикет
    stmt = select(Ticket).where(Ticket.product_id == product_id)
    result = await test_db.execute(stmt)
    tickets = result.scalars().all()
    assert len(tickets) == 1

    # Изменяем тикет в БД вручную, например переведем в IN_REVIEW
    tickets[0].status = "IN_REVIEW"
    await test_db.commit()

    # Второй запрос с тем же idempotency_key
    response2 = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": settings.B2B_TO_MODERATION_KEY},
        json={
            "event_type": "PRODUCT_CREATED",
            "idempotency_key": str(idempotency_key),
            "occurred_at": "2026-06-09T12:00:00Z",
            "payload": {
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "json_after": {}
            }
        }
    )
    assert response2.status_code == 202

    # Убеждаемся, что статус тикета НЕ изменился обратно на PENDING (запрос проигнорирован идемпотентно)
    await test_db.refresh(tickets[0])
    assert tickets[0].status == "IN_REVIEW"


@pytest.mark.asyncio
async def test_b2b_integration_error(client, monkeypatch):
    product_id = uuid.uuid4()
    seller_id = uuid.uuid4()

    # Ошибка запроса к B2B (например, таймаут)
    monkeypatch.setattr(httpx.AsyncClient, "get", AsyncMock(side_effect=httpx.TimeoutException("Timeout")))

    response = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": settings.B2B_TO_MODERATION_KEY},
        json={
            "event_type": "PRODUCT_CREATED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-09T12:00:00Z",
            "payload": {
                "product_id": str(product_id),
                "seller_id": str(seller_id),
                "json_after": {}
            }
        }
    )
    assert response.status_code == 500
    assert response.json()["code"] == "B2B_INTEGRATION_ERROR"
