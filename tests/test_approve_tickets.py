import uuid
from datetime import datetime, timedelta, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx
from sqlalchemy import select

from src.config import settings
from src.modules.tickets.models import Ticket


def make_mock_b2b_product(product_id: uuid.UUID, has_skus=True):
    return {
        "id": str(product_id),
        "title": "Nike Air Max",
        "skus": [
            {
                "id": str(uuid.uuid4()),
                "name": "Air Max 42",
                "price": 100,
                "active_quantity": 5
            }
        ] if has_skus else []
    }


@pytest.mark.asyncio
async def test_approve_transitions_to_moderated_and_emits_event(client, test_db, moderator_headers, monkeypatch):
    ticket_id = uuid.uuid4()
    product_id = uuid.uuid4()
    mod_id = uuid.UUID("00000000-0000-0000-0000-000000000000")

    # Сеем тикет в IN_REVIEW для текущего модератора
    ticket = Ticket(
        id=ticket_id,
        product_id=product_id,
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="IN_REVIEW",
        assigned_moderator_id=mod_id,
        claim_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=20),
        json_after={"something": "yes"}
    )
    test_db.add(ticket)
    await test_db.commit()

    # Мокаем запросы к B2B
    mock_get_resp = MagicMock(spec=httpx.Response)
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = make_mock_b2b_product(product_id, has_skus=True)
    mock_get_resp.raise_for_status = MagicMock()

    mock_post_resp = MagicMock(spec=httpx.Response)
    mock_post_resp.status_code = 204
    mock_post_resp.raise_for_status = MagicMock()

    mock_requests = []
    original_send = httpx.AsyncClient.send

    async def mock_send(self, request, *args, **kwargs):
        url_str = str(request.url)
        if "http://test" in url_str:
            return await original_send(self, request, *args, **kwargs)

        mock_requests.append(request)
        if request.method == "GET" and f"/products/{product_id}" in url_str:
            return mock_get_resp
        if request.method == "POST" and "/moderation/events" in url_str:
            return mock_post_resp
        raise Exception(f"Unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(httpx.AsyncClient, "send", mock_send)

    # Вызываем approve
    response = await client.post(
        f"/api/v1/tickets/{ticket_id}/approve",
        headers=moderator_headers,
        json={"comment": "Approved comment"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "APPROVED"

    # Проверяем БД
    await test_db.refresh(ticket)
    assert ticket.status == "APPROVED"
    assert ticket.decision_comment == "Approved comment"
    assert ticket.decision_at is not None

    # Проверяем, что B2B эвент отправлен
    assert len(mock_requests) == 2
    post_req = [r for r in mock_requests if r.method == "POST"][0]
    assert post_req.headers["X-Service-Key"] == settings.B2B_TO_MODERATION_KEY


@pytest.mark.asyncio
async def test_approve_others_card_returns_403(client, test_db, moderator_headers):
    ticket_id = uuid.uuid4()
    product_id = uuid.uuid4()
    other_mod_id = uuid.uuid4()

    # Сеем тикет, назначенный другому модератору
    ticket = Ticket(
        id=ticket_id,
        product_id=product_id,
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="IN_REVIEW",
        assigned_moderator_id=other_mod_id,
        claim_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=20)
    )
    test_db.add(ticket)
    await test_db.commit()

    response = await client.post(
        f"/api/v1/tickets/{ticket_id}/approve",
        headers=moderator_headers,
        json={}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "NOT_ASSIGNED_MODERATOR"


@pytest.mark.asyncio
async def test_approve_after_edited_returns_409(client, test_db, moderator_headers):
    ticket_id = uuid.uuid4()
    product_id = uuid.uuid4()
    mod_id = uuid.UUID("00000000-0000-0000-0000-000000000000")

    # Сеем тикет, который не находится в статусе IN_REVIEW (например, PENDING)
    ticket = Ticket(
        id=ticket_id,
        product_id=product_id,
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="PENDING",
        assigned_moderator_id=mod_id,
        claim_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=20)
    )
    test_db.add(ticket)
    await test_db.commit()

    response = await client.post(
        f"/api/v1/tickets/{ticket_id}/approve",
        headers=moderator_headers,
        json={}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "TICKET_WRONG_STATUS"


@pytest.mark.asyncio
async def test_approve_without_sku_returns_409(client, test_db, moderator_headers, monkeypatch):
    ticket_id = uuid.uuid4()
    product_id = uuid.uuid4()
    mod_id = uuid.UUID("00000000-0000-0000-0000-000000000000")

    # Сеем тикет
    ticket = Ticket(
        id=ticket_id,
        product_id=product_id,
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="IN_REVIEW",
        assigned_moderator_id=mod_id,
        claim_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=20)
    )
    test_db.add(ticket)
    await test_db.commit()

    # Товар возвращается без SKU
    mock_get_resp = MagicMock(spec=httpx.Response)
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = make_mock_b2b_product(product_id, has_skus=False)
    mock_get_resp.raise_for_status = MagicMock()

    original_send = httpx.AsyncClient.send

    async def mock_send(self, request, *args, **kwargs):
        url_str = str(request.url)
        if "http://test" in url_str:
            return await original_send(self, request, *args, **kwargs)

        if request.method == "GET" and f"/products/{product_id}" in url_str:
            return mock_get_resp
        raise Exception(f"Unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(httpx.AsyncClient, "send", mock_send)

    response = await client.post(
        f"/api/v1/tickets/{ticket_id}/approve",
        headers=moderator_headers,
        json={}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PRODUCT_HAS_NO_SKUS"


@pytest.mark.asyncio
async def test_approve_b2b_down_returns_500_and_status_remains_in_review(client, test_db, moderator_headers, monkeypatch):
    ticket_id = uuid.uuid4()
    product_id = uuid.uuid4()
    mod_id = uuid.UUID("00000000-0000-0000-0000-000000000000")

    # Сеем тикет
    ticket = Ticket(
        id=ticket_id,
        product_id=product_id,
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="IN_REVIEW",
        assigned_moderator_id=mod_id,
        claim_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=20)
    )
    test_db.add(ticket)
    await test_db.commit()

    original_send = httpx.AsyncClient.send

    # Мокаем GET-запрос к B2B, возвращая таймаут
    async def mock_send(self, request, *args, **kwargs):
        url_str = str(request.url)
        if "http://test" in url_str:
            return await original_send(self, request, *args, **kwargs)
        raise httpx.TimeoutException("Timeout connection")

    monkeypatch.setattr(httpx.AsyncClient, "send", mock_send)

    response = await client.post(
        f"/api/v1/tickets/{ticket_id}/approve",
        headers=moderator_headers,
        json={}
    )
    assert response.status_code == 500
    assert response.json()["code"] == "B2B_INTEGRATION_ERROR"

    # Убеждаемся, что статус тикета остался IN_REVIEW (произошел rollback)
    await test_db.refresh(ticket)
    assert ticket.status == "IN_REVIEW"
