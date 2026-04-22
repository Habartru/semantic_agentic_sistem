"""
Сервис получения поисковых подсказок Google.

Использует неофициальный endpoint suggestqueries.google.com
для получения автодополнений поисковых запросов.
"""

import asyncio
import logging
import random
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class GoogleSuggestService:
    """Сервис получения поисковых подсказок Google."""

    def __init__(self):
        self.base_url = "http://suggestqueries.google.com/complete/search"
        self.client = httpx.AsyncClient(timeout=10.0, follow_redirects=True)

    async def get_suggestions(
        self,
        query: str,
        lang: str = "ru",
        country: str = "ru",
    ) -> list[str]:
        """
        Получить подсказки для одного запроса.

        Использует endpoint suggestqueries.google.com с параметром client=firefox
        для получения чистого JSON-ответа.

        Args:
            query: Исходный поисковый запрос.
            lang: Код языка (например, "ru", "en").
            country: Код страны (например, "ru", "us").

        Returns:
            Список строк-подсказок. При ошибке возвращает пустой список.
        """
        params = {
            "client": "firefox",
            "hl": lang,
            "gl": country,
            "q": query,
        }

        last_exception: Optional[Exception] = None

        for attempt in range(1, 4):
            try:
                logger.debug(
                    "Запрос подсказок Google для '%s' (попытка %s/3)",
                    query,
                    attempt,
                )
                response = await self.client.get(
                    self.base_url,
                    params=params,
                )
                response.raise_for_status()

                data = response.json()
                # Формат ответа: [query, [suggestions...]]
                if isinstance(data, list) and len(data) >= 2:
                    suggestions = data[1]
                    if isinstance(suggestions, list):
                        logger.info(
                            "Получено %s подсказок для '%s'",
                            len(suggestions),
                            query,
                        )
                        return suggestions

                logger.warning(
                    "Неожиданный формат ответа для '%s': %s",
                    query,
                    data,
                )
                return []

            except httpx.HTTPStatusError as exc:
                last_exception = exc
                logger.warning(
                    "HTTP-ошибка при получении подсказок для '%s' "
                    "(попытка %s/3): %s",
                    query,
                    attempt,
                    exc,
                )
            except httpx.RequestError as exc:
                last_exception = exc
                logger.warning(
                    "Сетевая ошибка при получении подсказок для '%s' "
                    "(попытка %s/3): %s",
                    query,
                    attempt,
                    exc,
                )
            except Exception as exc:
                last_exception = exc
                logger.warning(
                    "Неожиданная ошибка при получении подсказок для '%s' "
                    "(попытка %s/3): %s",
                    query,
                    attempt,
                    exc,
                )

            # Задержка перед повторной попыткой (кроме последней)
            if attempt < 3:
                delay = random.uniform(0.5, 1.5)
                logger.debug(
                    "Пауза %.2f сек перед повторной попыткой...",
                    delay,
                )
                await asyncio.sleep(delay)

        logger.error(
            "Не удалось получить подсказки для '%s' после 3 попыток: %s",
            query,
            last_exception,
        )
        return []

    async def get_expanded_suggestions(
        self,
        seed_keywords: list[str],
        depth: int = 2,
    ) -> list[str]:
        """
        Рекурсивное расширение ключевых слов через подсказки Google.

        Args:
            seed_keywords: Начальный список ключевых слов.
            depth: Глубина расширения.
                1 — подсказки только для seed-ключей.
                2 — подсказки для seed + подсказки для top-5
                      результатов каждого seed.

        Returns:
            Дедуплицированный список всех собранных подсказок.
        """
        if not seed_keywords:
            logger.warning("Пустой список seed-ключей, возвращаем пустой результат")
            return []

        all_results: set[str] = set()
        current_level = [kw.strip() for kw in seed_keywords if kw.strip()]

        for level in range(1, depth + 1):
            logger.info(
                "Уровень расширения %s: обработка %s ключей",
                level,
                len(current_level),
            )

            next_level: list[str] = []

            for keyword in current_level:
                suggestions = await self.get_suggestions(keyword)

                for suggestion in suggestions:
                    if suggestion not in all_results:
                        all_results.add(suggestion)
                        next_level.append(suggestion)

                # Задержка между запросами чтобы не забанили
                delay = random.uniform(0.5, 1.5)
                logger.debug(
                    "Пауза %.2f сек перед следующим запросом...",
                    delay,
                )
                await asyncio.sleep(delay)

            # Для следующего уровня берём только top-5 результатов
            if level < depth:
                current_level = next_level[:5]
            else:
                current_level = []

        result = sorted(all_results)
        logger.info(
            "Расширение завершено: собрано %s уникальных подсказок",
            len(result),
        )
        return result

    async def close(self) -> None:
        """Закрыть HTTP-клиент и освободить ресурсы."""
        await self.client.aclose()
        logger.debug("HTTP-клиент GoogleSuggestService закрыт")
