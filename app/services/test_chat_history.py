"""Хранение истории тестового чата в памяти. Очищается при обновлении тестового промпта."""
from typing import Dict, List, Tuple
from uuid import UUID

_TEST_HISTORY_LIMIT = 10
_storage: Dict[Tuple[UUID, str], List[dict]] = {}


def get_test_history(tenant_id: UUID, user_id: str) -> List[dict]:
    return list(_storage.get((tenant_id, user_id)) or [])


def save_test_history(tenant_id: UUID, user_id: str, history: List[dict]) -> None:
    if not history:
        _storage.pop((tenant_id, user_id), None)
        return
    _storage[(tenant_id, user_id)] = history[-_TEST_HISTORY_LIMIT:]


def clear_tenant_test_history(tenant_id: UUID) -> None:
    """Очистить историю тестового чата для всех пользователей тенанта. Вызывать после сохранения тестового промпта."""
    keys_to_remove = [k for k in _storage if k[0] == tenant_id]
    for k in keys_to_remove:
        del _storage[k]
