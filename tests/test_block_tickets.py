import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from unittest.mock import MagicMock

from src.config import settings
from src.modules.blocking_reasons.models import SEED_REASONS
from src.modules.tickets.models import Ticket


SOFT_REASON_ID = SEED_REASONS[0]["id"]
HARD_REASON_ID = SEED_REASONS[7]["id"]
MOD_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
SKU_ID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"


def make_block_payload(
    reason_ids=None,
    comment="Описание и фото не соответствуют товару",
    field_reports=None,
):
    if reason_ids is None:
        reason_ids = [SOFT_REASON_ID]
    if field_reports is None:
        field_reports = [
            {
                "field_path": "description",
                "message": "Текст описания скопирован с другого товара",
                "severity": "ERROR",
            },
            {
                "field_path": f"skus/{SKU_ID}/price",
                "message": "Цена подозрительно низкая для данного бренда",
                "severity": "ERROR",
            },
        ]
    return {
        "blocking_reason_ids": reason_ids,
        "comment": comment,
        "field_reports": field_reports,
    }


async def seed_in_review_ticket(test_db, ticket_id=None, moderator_id=MOD_ID):
    ticket_id = ticket_id or uuid.uuid4()
    ticket = Ticket(
        id=ticket_id,
        product_id=uuid.uuid4(),
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


@pytest.mark.asyncio
async def test_soft_block_transitions_to_blocked_with_field_reports(
    client, test_db, moderator_headers, monkeypatch
):
    ticket = await seed_in_review_ticket(test_db)
    install_b2b_mock(monkeypatch)

    response = await client.post(
        f"/api/v1/tickets/{ticket.id}/block",
        headers=moderator_headers,
        json=make_block_payload(),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "BLOCKED"

    stmt = (
        select(Ticket)
        .options(
            selectinload(Ticket.blocking_reasons),
            selectinload(Ticket.field_reports),
        )
        .where(Ticket.id == ticket.id)
    )
    result = await test_db.execute(stmt)
    refreshed = result.scalar_one()

    assert refreshed.status == "BLOCKED"
    assert refreshed.decision_at is not None
    assert refreshed.decision_comment == "Описание и фото не соответствуют товару"
    assert len(refreshed.blocking_reasons) == 1
    assert str(refreshed.blocking_reasons[0].id) == SOFT_REASON_ID
    assert len(refreshed.field_reports) == 2
    assert refreshed.field_reports[0].field_path == "description"
    assert refreshed.field_reports[1].field_path == f"skus/{SKU_ID}/price"


@pytest.mark.asyncio
async def test_soft_block_emits_event_to_b2b(client, test_db, moderator_headers, monkeypatch):
    ticket = await seed_in_review_ticket(test_db)
    mock_requests = []
    install_b2b_mock(monkeypatch, capture_requests=mock_requests)

    response = await client.post(
        f"/api/v1/tickets/{ticket.id}/block",
        headers=moderator_headers,
        json=make_block_payload(),
    )

    assert response.status_code == 200
    assert len(mock_requests) == 1

    post_req = mock_requests[0]
    assert post_req.method == "POST"
    assert "/moderation/events" in str(post_req.url)
    assert post_req.headers["X-Service-Key"] == settings.B2B_TO_MODERATION_KEY

    body = json.loads(post_req.content.decode())
    assert body["event_type"] == "BLOCKED"
    assert body["hard_block"] is False
    assert body["product_id"] == str(ticket.product_id)
    assert body["blocking_reason_id"] == SOFT_REASON_ID
    assert body["moderator_comment"] == "Описание и фото не соответствуют товару"
    assert len(body["field_reports"]) == 2
    assert body["field_reports"][0]["field_name"] == "description"
    assert body["field_reports"][1]["field_name"] == "sku_price"
    assert body["field_reports"][1]["sku_id"] == SKU_ID


@pytest.mark.asyncio
async def test_soft_block_unknown_reason_returns_400(client, test_db, moderator_headers, monkeypatch):
    ticket = await seed_in_review_ticket(test_db)
    install_b2b_mock(monkeypatch)

    response = await client.post(
        f"/api/v1/tickets/{ticket.id}/block",
        headers=moderator_headers,
        json=make_block_payload(reason_ids=[str(uuid.uuid4())]),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "BLOCKING_REASON_NOT_FOUND"


@pytest.mark.asyncio
async def test_soft_block_others_card_returns_403(client, test_db, moderator_headers, monkeypatch):
    ticket = await seed_in_review_ticket(test_db, moderator_id=uuid.uuid4())
    install_b2b_mock(monkeypatch)

    response = await client.post(
        f"/api/v1/tickets/{ticket.id}/block",
        headers=moderator_headers,
        json=make_block_payload(),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_ASSIGNED_MODERATOR"


@pytest.mark.asyncio
async def test_soft_block_invalid_field_name_returns_400(client, test_db, moderator_headers, monkeypatch):
    ticket = await seed_in_review_ticket(test_db)
    install_b2b_mock(monkeypatch)

    response = await client.post(
        f"/api/v1/tickets/{ticket.id}/block",
        headers=moderator_headers,
        json=make_block_payload(
            field_reports=[
                {
                    "field_path": "invalid_field",
                    "message": "Bad field",
                    "severity": "ERROR",
                }
            ]
        ),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_FIELD_REPORT"


@pytest.mark.asyncio
async def test_block_with_hard_reason_transitions_to_hard_blocked(
    client, test_db, moderator_headers, monkeypatch
):
    """Hard-причина в /block переводит тикет в HARD_BLOCKED, а не возвращает 400."""
    ticket = await seed_in_review_ticket(test_db)
    install_b2b_mock(monkeypatch)

    response = await client.post(
        f"/api/v1/tickets/{ticket.id}/block",
        headers=moderator_headers,
        json=make_block_payload(reason_ids=[HARD_REASON_ID]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "HARD_BLOCKED"
