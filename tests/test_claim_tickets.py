import uuid
import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.modules.tickets.models import Ticket
from src.modules.tickets.service import TicketService


@pytest.mark.asyncio
async def test_claim_next_happy_path(client, test_db, moderator_headers):
    # Декодируем ID модератора из заголовков (он сгенерирован с сабом "00000000-0000-0000-0000-000000000000")
    mod_id = uuid.UUID("00000000-0000-0000-0000-000000000000")

    # Удалим все старые тикеты, чтобы тест был чистым
    await test_db.execute(delete(Ticket))
    await test_db.commit()

    # Сеем два тикета:
    # Тикет A: приоритет 2, создан раньше
    ticket_a = Ticket(
        id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="PENDING",
        queue_priority=2,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    )
    # Тикет B: приоритет 1 (высший), создан позже
    ticket_b = Ticket(
        id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="PENDING",
        queue_priority=1,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    test_db.add(ticket_a)
    test_db.add(ticket_b)
    await test_db.commit()

    # Запрашиваем следующий тикет
    response = await client.post("/api/v1/queue/claim", headers=moderator_headers, json={})
    assert response.status_code == 200
    data = response.json()

    # Должен вернуться Тикет B, так как у него приоритет выше (1 < 2)
    assert data["id"] == str(ticket_b.id)
    assert data["status"] == "IN_REVIEW"
    assert data["assigned_moderator_id"] == str(mod_id)

    # Проверяем TTL блокировки
    claimed_at = datetime.fromisoformat(data["claimed_at"].replace("Z", ""))
    claim_expires_at = datetime.fromisoformat(data["claim_expires_at"].replace("Z", ""))
    diff = claim_expires_at - claimed_at
    assert abs(diff.total_seconds() - 1800) < 5  # около 30 минут (1800 сек)


@pytest.mark.asyncio
async def test_empty_queue_returns_204(client, test_db, moderator_headers):
    # Очищаем очередь
    await test_db.execute(delete(Ticket))
    await test_db.commit()

    response = await client.post("/api/v1/queue/claim", headers=moderator_headers, json={})
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_moderator_has_active_returns_409(client, test_db, moderator_headers):
    mod_id = uuid.UUID("00000000-0000-0000-0000-000000000000")

    # Сеем активный тикет в IN_REVIEW для текущего модератора
    active_ticket = Ticket(
        id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="IN_REVIEW",
        queue_priority=3,
        assigned_moderator_id=mod_id,
        claim_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=20)
    )
    test_db.add(active_ticket)
    await test_db.commit()

    response = await client.post("/api/v1/queue/claim", headers=moderator_headers, json={})
    assert response.status_code == 409
    assert response.json()["code"] == "MODERATOR_ALREADY_HAS_ACTIVE_TICKET"


@pytest.mark.asyncio
async def test_claim_expired_ticket(client, test_db, moderator_headers):
    # Сеем тикет, который висит в IN_REVIEW у другого модератора, но срок его блокировки истек
    expired_ticket = Ticket(
        id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        seller_id=uuid.uuid4(),
        kind="CREATE",
        status="IN_REVIEW",
        queue_priority=3,
        assigned_moderator_id=uuid.uuid4(),
        claim_expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)  # истек 5 минут назад
    )
    test_db.add(expired_ticket)
    await test_db.commit()

    response = await client.post("/api/v1/queue/claim", headers=moderator_headers, json={})
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == str(expired_ticket.id)
    assert data["status"] == "IN_REVIEW"
    assert data["assigned_moderator_id"] == "00000000-0000-0000-0000-000000000000"


@pytest.mark.asyncio
async def test_claim_with_priority_and_category_filters(client, test_db, moderator_headers):
    await test_db.execute(delete(Ticket))
    await test_db.commit()

    cat1 = uuid.uuid4()
    cat2 = uuid.uuid4()

    # Ticket A: priority 1, category cat1
    ticket_a = Ticket(
        id=uuid.uuid4(), product_id=uuid.uuid4(), seller_id=uuid.uuid4(),
        category_id=cat1, kind="CREATE", status="PENDING", queue_priority=1,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
    )
    # Ticket B: priority 2, category cat2
    ticket_b = Ticket(
        id=uuid.uuid4(), product_id=uuid.uuid4(), seller_id=uuid.uuid4(),
        category_id=cat2, kind="CREATE", status="PENDING", queue_priority=2,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    )
    # Ticket C: priority 1, category cat2
    ticket_c = Ticket(
        id=uuid.uuid4(), product_id=uuid.uuid4(), seller_id=uuid.uuid4(),
        category_id=cat2, kind="CREATE", status="PENDING", queue_priority=1,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    test_db.add_all([ticket_a, ticket_b, ticket_c])
    await test_db.commit()

    # 1. Фильтр по приоритету 2 -> возвращает Ticket B
    resp1 = await client.post(
        "/api/v1/queue/claim",
        headers=moderator_headers,
        json={"queue_priority": 2}
    )
    assert resp1.status_code == 200
    assert resp1.json()["id"] == str(ticket_b.id)

    # Вернем Ticket B в PENDING для следующих тестов
    await test_db.execute(
        delete(Ticket).where(Ticket.id.in_([ticket_a.id, ticket_b.id, ticket_c.id]))
    )
    await test_db.commit()

    # Посеем заново для чистоты следующего фильтра
    ticket_a = Ticket(
        id=uuid.uuid4(), product_id=uuid.uuid4(), seller_id=uuid.uuid4(),
        category_id=cat1, kind="CREATE", status="PENDING", queue_priority=1
    )
    ticket_b = Ticket(
        id=uuid.uuid4(), product_id=uuid.uuid4(), seller_id=uuid.uuid4(),
        category_id=cat2, kind="CREATE", status="PENDING", queue_priority=2
    )
    ticket_c = Ticket(
        id=uuid.uuid4(), product_id=uuid.uuid4(), seller_id=uuid.uuid4(),
        category_id=cat2, kind="CREATE", status="PENDING", queue_priority=1
    )
    test_db.add_all([ticket_a, ticket_b, ticket_c])
    await test_db.commit()

    # 2. Фильтр по категории cat2 -> возвращает Ticket C (приоритет 1 выше чем у B)
    resp2 = await client.post(
        "/api/v1/queue/claim",
        headers=moderator_headers,
        json={"category_ids": [str(cat2)]}
    )
    assert resp2.status_code == 200
    assert resp2.json()["id"] == str(ticket_c.id)


@pytest.mark.asyncio
async def test_concurrent_claims_different_cards(test_engine):
    # Очищаем таблицу перед тестом конкурентности
    async with test_engine.begin() as conn:
        await conn.execute(delete(Ticket))

    # Сеем два тикета:
    ticket1_id = uuid.uuid4()
    ticket2_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            Ticket.__table__.insert().values(
                id=ticket1_id,
                product_id=uuid.uuid4(),
                seller_id=uuid.uuid4(),
                kind="CREATE",
                status="PENDING",
                queue_priority=1,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
            )
        )
        await conn.execute(
            Ticket.__table__.insert().values(
                id=ticket2_id,
                product_id=uuid.uuid4(),
                seller_id=uuid.uuid4(),
                kind="CREATE",
                status="PENDING",
                queue_priority=1,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None)
            )
        )

    # Создаем два параллельных соединения
    conn1 = await test_engine.connect()
    conn2 = await test_engine.connect()

    session_factory1 = async_sessionmaker(bind=conn1, class_=AsyncSession)
    session_factory2 = async_sessionmaker(bind=conn2, class_=AsyncSession)

    session1 = session_factory1()
    session2 = session_factory2()

    mod1 = uuid.uuid4()
    mod2 = uuid.uuid4()

    try:
        # Вызываем одновременно claim_ticket в параллельных тасках
        task1 = TicketService.claim_ticket(session1, mod1)
        task2 = TicketService.claim_ticket(session2, mod2)

        res1, res2 = await asyncio.gather(task1, task2)

        # Оба должны успешно взять тикеты
        assert res1 is not None
        assert res2 is not None

        # Тикеты должны быть РАЗНЫМИ
        assert res1.id != res2.id
        assert {res1.id, res2.id} == {ticket1_id, ticket2_id}

    finally:
        await session1.close()
        await session2.close()
        await conn1.close()
        await conn2.close()

        # Очистка
        async with test_engine.begin() as conn:
            await conn.execute(delete(Ticket))
