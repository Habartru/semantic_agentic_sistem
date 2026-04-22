"""
Сервис получения данных из Google Trends.

Использует библиотеку pytrends для получения связанных запросов и тем.
"""

import logging
import time
from typing import Optional

from pytrends.request import TrendReq

logger = logging.getLogger(__name__)


class TrendsService:
    """Сервис получения данных Google Trends."""

    def __init__(self):
        # hl='ru' — русский язык интерфейса
        # tz=180 — московский часовой пояс (UTC+3 в минутах)
        self.pytrends = TrendReq(hl="ru", tz=180)

    def _safe_build_payload(
        self,
        keywords: list[str],
        geo: str = "RU",
    ) -> bool:
        """
        Безопасная сборка payload с обработкой ошибок.

        Args:
            keywords: Список ключевых слов (максимум 5).
            geo: Код региона.

        Returns:
            True если успешно, иначе False.
        """
        try:
            self.pytrends.build_payload(kw_list=keywords, geo=geo)
            return True
        except Exception as exc:
            logger.error(
                "Ошибка при сборке payload для ключей %s: %s",
                keywords,
                exc,
            )
            return False

    def get_related_queries(
        self,
        keywords: list[str],
        geo: str = "RU",
    ) -> dict[str, dict[str, list[str]]]:
        """
        Получить связанные запросы (top + rising) для списка ключей.

        pytrends ограничивает запрос 5 ключами за раз,
        поэтому разбиваем на батчи.

        Args:
            keywords: Список ключевых слов для анализа.
            geo: Код региона (по умолчанию "RU").

        Returns:
            Словарь формата:
            {
                keyword: {
                    "top": [query1, query2, ...],
                    "rising": [query1, query2, ...],
                }
            }
            При ошибке возвращает пустой словарь.
        """
        if not keywords:
            logger.warning("Пустой список ключей для анализа Trends")
            return {}

        results: dict[str, dict[str, list[str]]] = {}

        # Разбиваем на батчи по 5 ключей (ограничение pytrends)
        batch_size = 5
        for i in range(0, len(keywords), batch_size):
            batch = keywords[i : i + batch_size]
            logger.info(
                "Обработка батча %s/%s: %s",
                i // batch_size + 1,
                (len(keywords) - 1) // batch_size + 1,
                batch,
            )

            if not self._safe_build_payload(batch, geo=geo):
                continue

            try:
                related = self.pytrends.related_queries()
            except Exception as exc:
                logger.error(
                    "Ошибка при получении related_queries для %s: %s",
                    batch,
                    exc,
                )
                # Пауза при ошибке 429 (rate limit)
                if "429" in str(exc) or "Too many requests" in str(exc):
                    logger.warning(
                        "Обнаружен rate limit, пауза 60 сек..."
                    )
                    time.sleep(60)
                continue

            if related is None:
                logger.warning("Пустой ответ related_queries для %s", batch)
                continue

            for keyword in batch:
                keyword_data = related.get(keyword)
                if keyword_data is None:
                    logger.debug(
                        "Нет данных для ключа '%s' в ответе Trends",
                        keyword,
                    )
                    continue

                top_df = keyword_data.get("top")
                rising_df = keyword_data.get("rising")

                top_queries: list[str] = []
                rising_queries: list[str] = []

                if top_df is not None and not top_df.empty:
                    top_queries = top_df["query"].tolist()

                if rising_df is not None and not rising_df.empty:
                    rising_queries = rising_df["query"].tolist()

                results[keyword] = {
                    "top": top_queries,
                    "rising": rising_queries,
                }
                logger.info(
                    "Ключ '%s': top=%s, rising=%s",
                    keyword,
                    len(top_queries),
                    len(rising_queries),
                )

            # Пауза между батчами чтобы не получить бан
            if i + batch_size < len(keywords):
                pause = 5.0
                logger.debug("Пауза %.1f сек перед следующим батчем...", pause)
                time.sleep(pause)

        return results

    def get_related_topics(
        self,
        keywords: list[str],
        geo: str = "RU",
    ) -> dict[str, dict[str, list[str]]]:
        """
        Получить связанные темы (related topics) для списка ключей.

        Args:
            keywords: Список ключевых слов для анализа.
            geo: Код региона (по умолчанию "RU").

        Returns:
            Словарь формата:
            {
                keyword: {
                    "top": [topic1, topic2, ...],
                    "rising": [topic1, topic2, ...],
                }
            }
            При ошибке возвращает пустой словарь.
        """
        if not keywords:
            logger.warning("Пустой список ключей для анализа related_topics")
            return {}

        results: dict[str, dict[str, list[str]]] = {}
        batch_size = 5

        for i in range(0, len(keywords), batch_size):
            batch = keywords[i : i + batch_size]
            logger.info(
                "Обработка батча related_topics %s/%s: %s",
                i // batch_size + 1,
                (len(keywords) - 1) // batch_size + 1,
                batch,
            )

            if not self._safe_build_payload(batch, geo=geo):
                continue

            try:
                related = self.pytrends.related_topics()
            except Exception as exc:
                logger.error(
                    "Ошибка при получении related_topics для %s: %s",
                    batch,
                    exc,
                )
                if "429" in str(exc) or "Too many requests" in str(exc):
                    logger.warning(
                        "Обнаружен rate limit, пауза 60 сек..."
                    )
                    time.sleep(60)
                continue

            if related is None:
                logger.warning("Пустой ответ related_topics для %s", batch)
                continue

            for keyword in batch:
                keyword_data = related.get(keyword)
                if keyword_data is None:
                    continue

                top_df = keyword_data.get("top")
                rising_df = keyword_data.get("rising")

                top_topics: list[str] = []
                rising_topics: list[str] = []

                if top_df is not None and not top_df.empty:
                    # Берём название темы из колонки topic_title
                    if "topic_title" in top_df.columns:
                        top_topics = top_df["topic_title"].dropna().tolist()
                    elif "title" in top_df.columns:
                        top_topics = top_df["title"].dropna().tolist()

                if rising_df is not None and not rising_df.empty:
                    if "topic_title" in rising_df.columns:
                        rising_topics = (
                            rising_df["topic_title"].dropna().tolist()
                        )
                    elif "title" in rising_df.columns:
                        rising_topics = (
                            rising_df["title"].dropna().tolist()
                        )

                results[keyword] = {
                    "top": top_topics,
                    "rising": rising_topics,
                }
                logger.info(
                    "Ключ '%s': top_topics=%s, rising_topics=%s",
                    keyword,
                    len(top_topics),
                    len(rising_topics),
                )

            if i + batch_size < len(keywords):
                pause = 5.0
                logger.debug("Пауза %.1f сек перед следующим батчем...", pause)
                time.sleep(pause)

        return results
