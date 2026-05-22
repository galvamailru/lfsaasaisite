#!/usr/bin/env python3
"""Проверка отправки trace в LangFuse. Запуск: docker compose run --rm app python scripts/check_langfuse.py"""
from langfuse import get_client, propagate_attributes

from app.config import settings
from app.langfuse_tracing import _sync_env_from_settings, is_enabled, _base_url


def main() -> None:
    print("enabled:", is_enabled())
    print("base_url:", _base_url())
    print("public_key prefix:", (settings.langfuse_public_key or "")[:12] + "...")
    if not is_enabled():
        print("FAIL: LangFuse not configured in .env")
        return
    _sync_env_from_settings()
    client = get_client()
    with propagate_attributes(session_id="check-script", user_id="test"):
        with client.start_as_current_observation(as_type="span", name="connectivity-check") as span:
            with client.start_as_current_observation(
                as_type="generation", name="ping", model="test"
            ) as gen:
                gen.update(input="ping", output="pong")
            span.update(output="ok")
    client.flush()
    print("OK: test trace sent — open LangFuse UI → Tracing, filter last 5 minutes, name connectivity-check")


if __name__ == "__main__":
    main()
