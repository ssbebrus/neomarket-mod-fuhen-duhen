# US-MOD-01: Приём событий о товаре от B2B

Этот пулл-реквест реализует приём и обработку входящих событий об изменении товаров от B2B-сервиса. Все изменения разделены по слоям в соответствии с модульной 4-слойной архитектурой проекта.

---

## 🏛️ Architectural Decision Record (ADR)
**Выбор формата хранения изменений в карточке модерации ("что было / что стало")**

**Варианты:**
1. **Снапшоты `json_before` + `json_after`** *(Выбранный вариант)*.
2. **Полный снапшот только `json_after`**.
3. **Дельта изменений (delta)**.

**Критерии выбора:**
- **Сложность диагностики инцидентов**: Наличие двух снимков (`json_before` и `json_after`) позволяет мгновенно понять, что именно изменилось в товаре, без необходимости искать предыдущие версии.
- **Удобство для модератора**: Интерфейс модератора может легко отрендерить визуальный дифференциал (diff) полей на основе двух полных JSON-снимков.
- **Сложность вычислений**: Расчет дельты (delta) на сервере или восстановление состояния по цепочке дельт требует дополнительных вычислительных ресурсов.

**Решение:** Выбран вариант **1**. При создании тикета (`CREATED`) `json_before` равен `null`. При редактировании (`EDITED`) предыдущий `json_after` переносится в `json_before`, а новый снимок от B2B записывается в `json_after`.

---

## 📁 Изменения в проекте

### 🛠️ Новые и измененные файлы
* **`/src/modules/b2b_events/models.py`**: Создана модель `EventIdempotencyKey` для сохранения ключей идемпотентности событий (TTL 24 часа).
* **`/src/modules/b2b_events/schemas.py`**: Описаны схемы валидации `IncomingB2BEvent` и Payload (`EventProductCreatedPayload`, `EventProductEditedPayload`, `EventProductDeletedPayload`) с дискриминативной валидацией по `event_type`.
* **`/src/modules/b2b_events/service.py`**: Реализован класс `B2BEventService`:
  - Проверка идемпотентности по `idempotency_key`.
  - Запросы к B2B-сервису через `httpx.AsyncClient` с передачей `X-Service-Key`.
  - Приоритеты для `EDITED` событий (2 при BLOCKED, 3 при APPROVED с активным стоком, 4 при APPROVED без активного стока).
  - Сброс статуса в `PENDING`, очистка модератора и причин блокировки.
  - Каскадное удаление тикета при событии `PRODUCT_DELETED`.
* **`/src/modules/b2b_events/router.py`**: Добавлен эндпоинт `POST /events` (с префиксом `/b2b`), проверка `X-Service-Key` и обработка исключений.
* **`/src/core/exceptions.py`**: Добавлены доменные исключения: `DuplicateCreatedEvent`, `TicketNotFound`, `B2BIntegrationError`, `InvalidServiceKey`.
* **`/src/db/__init__.py`**: Зарегистрирована модель `EventIdempotencyKey`.
* **`/src/api/router.py`**: Подключен роутер `/b2b` с тегом `B2B Events`.
* **`/tests/test_b2b_events.py`**: Набор тестов для полной проверки эндпоинта.

---

## 🧪 Тест-кейсы

Для валидации разработаны следующие автотесты в `/tests/test_b2b_events.py`:

1. `test_missing_service_header_401` — Проверка отсутствия/невалидности заголовка `X-Service-Key` (возврат HTTP 401).
2. `test_created_pending` — Создание карточки тикета со статусом `PENDING` при событии `PRODUCT_CREATED`.
3. `test_edited_returns_to_review` — Возвращение тикета в статус `PENDING` при `PRODUCT_EDITED` с перерасчетом приоритета (2 при BLOCKED, 3 при APPROVED и stock > 0, 4 при APPROVED и stock == 0).
4. `test_edited_updates_in_review` — Сброс назначенного модератора и перевод тикета в `PENDING` при изменении товара во время `IN_REVIEW`.
5. `test_deleted_archived` — Физическое удаление карточки тикета из БД при событии `PRODUCT_DELETED`.
6. `test_duplicate_event_no_side_effects` — Проверка идемпотентности повторных запросов с одинаковым `idempotency_key` (возврат HTTP 202 без побочных эффектов).
7. `test_b2b_integration_error` — Проверка возврата HTTP 500 при недоступности или ошибках B2B-сервиса.

### Результат выполнения pytest в контейнере:
```bash
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.0.3, pluggy-1.6.0
rootdir: /app
configfile: pytest.ini
plugins: asyncio-1.3.0, anyio-4.12.1
collected 12 items

tests/test_b2b_events.py .......                                         [ 58%]
tests/test_blocking_reasons.py ....                                      [ 91%]
tests/test_health.py .                                                   [100%]

============================== 12 passed in 0.97s ==============================
```
