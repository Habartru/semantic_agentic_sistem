"""
Модуль конфигурации приложения.
Загружает настройки из переменных окружения и .env файла.
Поддерживает получение настроек из БД с fallback на env.
"""

import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()


class AppConfig:
    """Класс настроек приложения."""

    # Ключ API для OpenRouter (обязательный)
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

    # Модель OpenRouter по умолчанию
    OPENROUTER_MODEL: str = os.getenv(
        "OPENROUTER_MODEL",
        "anthropic/claude-sonnet-4"
    )

    # URL подключения к базе данных (async SQLite)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./seo_agents.db"
    )


# Глобальный экземпляр настроек
settings = AppConfig()


async def get_setting(key: str, default: str | None = None) -> str | None:
    """
    Получить настройку из БД с fallback на переменные окружения.

    Args:
        key: Ключ настройки (например, "openrouter_api_key").
        default: Значение по умолчанию, если не найдено ни в БД, ни в env.

    Returns:
        Значение настройки или default.
    """
    from app.database import AsyncSessionLocal
    from app.models import Settings as SettingsModel
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SettingsModel).where(SettingsModel.key == key)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            return row.value

    # Fallback на переменные окружения
    env_key = key.upper()
    env_value = os.getenv(env_key)
    if env_value is not None:
        return env_value

    # Fallback на атрибуты AppConfig
    config_value = getattr(settings, env_key, None)
    if config_value is not None:
        return config_value

    return default
