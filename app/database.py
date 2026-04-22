"""
Модуль настройки асинхронного подключения к базе данных.
Использует SQLAlchemy с aiosqlite для асинхронной работы с SQLite.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.config import settings

# Базовый класс для ORM-моделей
Base = declarative_base()

# Создаём асинхронный движок SQLAlchemy
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Установите True для отладки SQL-запросов
    future=True
)

# Фабрика асинхронных сессий
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_db() -> AsyncSession:
    """
    Dependency injection для FastAPI.
    Предоставляет асинхронную сессию базы данных.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """
    Инициализация базы данных.
    Создаёт все таблицы на основе ORM-моделей.
    """
    from app import models  # Импорт моделей для регистрации метаданных
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
