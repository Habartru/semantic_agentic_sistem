"""
Сервис SERP-анализа (заглушка для MVP).

Полноценный анализ поисковой выдачи будет реализован
в следующей версии продукта.
"""

import logging

logger = logging.getLogger(__name__)


class SerpService:
    """Сервис SERP-анализа (заглушка для MVP)."""

    async def analyze_serp(self, query: str) -> dict:
        """
        Анализ поисковой выдачи — будет реализован позже.

        Args:
            query: Поисковый запрос для анализа.

        Returns:
            Заглушка с информацией о статусе.
        """
        logger.info(
            "SERP-анализ запрошен для '%s', но пока не реализован",
            query,
        )
        return {
            "query": query,
            "status": "not_implemented",
            "message": "SERP-анализ будет доступен в следующей версии",
        }
