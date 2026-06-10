import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from unittest.mock import MagicMock

from src.config import settings
from src.modules.blocking_reasons.models import SEED_REASONS
from src.modules.tickets.models import Ticket


# SEED_REASONS[7] = "Контрафактный товар", hard_block=True
HARD_REASON_ID = SEED_REASONS[7]["id"]
MOD_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def make_hard_block_payload(comment="Товар является контрафактом"):
    return {
        "blocking_reason_ids": [HARD_REASON_ID],
        "comment": comment,
        "field_reports": [],
    }


async def seed_in_review_ticket(test_db, ticket_id=None, moderator_id=MOD_ID):
    ticket_id = ticket_id or uuid.uuid4()
    product_id = uuid.uuid4()
    ticket = Ticket(
        id=ticket_id,
        product_id=product_id,
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="IN_REVIEW",
        assigned_moderator_id=moderator_id,
        claim_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=20),
        json_after={"title": "Test product"},
    )
    test_db.add(ticket)
    await test_db.commit()
    return ticket


def install_b2b_mock(monkeypatch, capture_requests=None):
    mock_post_resp = MagicMock(spec=httpx.Response)
    mock_post_resp.status_code = 204
    mock_post_resp.raise_for_status = MagicMock()

    original_send = httpx.AsyncClient.send

    async def mock_send(self, request, *args, **kwargs):
        url_str = str(request.url)
        if "http://test" in url_str:
            return await original_send(self, request, *args, **kwargs)
        if capture_requests is not None:
            capture_requests.append(request)
        if request.method == "POST" and "/moderation/events" in url_str:
            return mock_post_resp
        raise Exception(f"Unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(httpx.AsyncClient, "send", mock_send)


# ---------------------------------------------------------------------------
# 1. Happy path: статус → HARD_BLOCKED, событие уходит в B2B
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hard_block_transitions_to_terminal_and_emits_event(
    client, test_db, moderator_headers, monkeypatch
):
    ticket = await seed_in_review_ticket(test_db)
    install_b2b_mock(monkeypatch)

    response = await client.post(
        f"/api/v1/tickets/{ticket.id}/block",
        headers=moderator_headers,
        json=make_hard_block_payload(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "HARD_BLOCKED"

    # Проверяем состояние в БД
    await test_db.refresh(ticket)
    assert ticket.status == "HARD_BLOCKED"
    assert ticket.decision_at is not None
    assert ticket.decision_comment == "Товар является контрафактом"


# ---------------------------------------------------------------------------
# 2. Флаг hard_block=true корректно передаётся в payload B2B
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hard_block_event_carries_hard_block_true(
    client, test_db, moderator_headers, monkeypatch
):
    ticket = await seed_in_review_ticket(test_db)
    mock_requests = []
    install_b2b_mock(monkeypatch, capture_requests=mock_requests)

    response = await client.post(
        f"/api/v1/tickets/{ticket.id}/block",
        headers=moderator_headers,
        json=make_hard_block_payload(),
    )

    assert response.status_code == 200
    assert len(mock_requests) == 1

    post_req = mock_requests[0]
    assert post_req.method == "POST"
    assert "/moderation/events" in str(post_req.url)
    assert post_req.headers["X-Service-Key"] == settings.B2B_TO_MODERATION_KEY

    body = json.loads(post_req.content.decode())
    assert body["event_type"] == "BLOCKED"
    assert body["hard_block"] is True
    assert body["product_id"] == str(ticket.product_id)
    assert body["blocking_reason_id"] == HARD_REASON_ID


# ---------------------------------------------------------------------------
# 3. Любая попытка мутировать HARD_BLOCKED тикет → 409
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_any_modify_on_hard_blocked_returns_409(
    client, test_db, moderator_headers, monkeypatch
):
    # Сеем тикет сразу в HARD_BLOCKED
    ticket_id = uuid.uuid4()
    ticket = Ticket(
        id=ticket_id,
        product_id=uuid.uuid4(),
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="HARD_BLOCKED",
        assigned_moderator_id=MOD_ID,
        claim_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=20),
        json_after={"title": "Blocked product"},
    )
    test_db.add(ticket)
    await test_db.commit()

    install_b2b_mock(monkeypatch)

    # /approve → 409
    resp_approve = await client.post(
        f"/api/v1/tickets/{ticket_id}/approve",
        headers=moderator_headers,
        json={},
    )
    assert resp_approve.status_code == 409
    assert resp_approve.json()["code"] == "TICKET_WRONG_STATUS"

    # /block → 409
    resp_block = await client.post(
        f"/api/v1/tickets/{ticket_id}/block",
        headers=moderator_headers,
        json=make_hard_block_payload(),
    )
    assert resp_block.status_code == 409
    assert resp_block.json()["code"] == "TICKET_WRONG_STATUS"


# ---------------------------------------------------------------------------
# 4. PRODUCT_EDITED для HARD_BLOCKED товара игнорируется (200 OK, статус не меняется)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_edited_event_on_hard_blocked_is_ignored(client, test_db):
    """PRODUCT_EDITED на HARD_BLOCKED товар игнорируется — статус не меняется."""
    product_id = uuid.uuid4()
    ticket = Ticket(
        id=uuid.uuid4(),
        product_id=product_id,
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="HARD_BLOCKED",
        json_after={"title": "Blocked product"},
    )
    test_db.add(ticket)
    await test_db.commit()

    # Для HARD_BLOCKED b2b_events service делает `pass` без fetch к B2B — мок не нужен
    idempotency_key = str(uuid.uuid4())
    response = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": settings.B2B_TO_MODERATION_KEY},
        json={
            "idempotency_key": idempotency_key,
            "event_type": "PRODUCT_EDITED",
            "occurred_at": "2026-06-10T10:00:00Z",
            "payload": {
                "product_id": str(product_id),
                "seller_id": str(uuid.uuid4()),
                "category_id": None,
                "queue_priority": 3,
                "json_before": {"title": "Old title"},
                "json_after": {"title": "New title"},
            },
        },
    )

    assert response.status_code == 202

    # Статус должен остаться HARD_BLOCKED
    await test_db.refresh(ticket)
    assert ticket.status == "HARD_BLOCKED"


# ---------------------------------------------------------------------------
# 5. PRODUCT_DELETED удаляет запись тикета из БД
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deleted_event_removes_hard_blocked(client, test_db):
    product_id = uuid.uuid4()
    ticket_id = uuid.uuid4()
    ticket = Ticket(
        id=ticket_id,
        product_id=product_id,
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="HARD_BLOCKED",
        json_after={"title": "Blocked product"},
    )
    test_db.add(ticket)
    await test_db.commit()

    idempotency_key = str(uuid.uuid4())
    response = await client.post(
        "/api/v1/b2b/events",
        headers={"X-Service-Key": settings.B2B_TO_MODERATION_KEY},
        json={
            "idempotency_key": idempotency_key,
            "event_type": "PRODUCT_DELETED",
            "occurred_at": "2026-06-10T10:00:00Z",
            "payload": {
                "product_id": str(product_id),
            },
        },
    )

    assert response.status_code == 202

    # Тикет должен быть удалён из БД
    result = await test_db.execute(select(Ticket).where(Ticket.id == ticket_id))
    assert result.scalar_one_or_none() is None
