"""
Агент расширения семантического ядра — ExpansionAgent.

Итеративный цикл расширения ключевых слов через Google Suggest,
Google Trends и LLM. Выполняет 2 итерации для максимального охвата.
"""

import asyncio
from typing import Dict, Any, List, Set

from app.agents.base import BaseAgent
from app.services.google_suggest import GoogleSuggestService
from app.services.trends import TrendsService
from app.services.llm import LLMService


class ExpansionAgent(BaseAgent):
    """
    Агент расширения семантического ядра.

    Input:
        - seed_keywords: список стартовых ключей
        - business_context: описание бизнеса
        - geo: гео-таргетинг

    Output:
        - candidates: список всех кандидатов
        - sources: словарь источников для каждого кандидата
    """

    name = "ExpansionAgent"
    description = "Итеративное расширение семантического ядра"

    def __init__(self):
        """Инициализация агента с сервисами расширения."""
        super().__init__()
        self.suggest_service = GoogleSuggestService()
        self.trends_service = TrendsService()
        self.llm_service = LLMService()

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнить итеративное расширение ключевых слов (2 итерации).

        Args:
            input_data: Входные данные с seed_keywords, business_context, geo.

        Returns:
            Словарь с candidates и sources.
        """
        seed_keywords = input_data.get("seed_keywords", []) or []
        business_context = input_data.get("business_context", "")
        geo = input_data.get("geo", "Москва")

        self._log(f"Начало расширения: {len(seed_keywords)} seed-ключей")

        all_candidates: Set[str] = set()
        sources: Dict[str, List[str]] = {}

        # ===================== ИТЕРАЦИЯ 1 =====================
        self._log("--- Итерация 1 ---")

        # 1.1 Google Suggest для seed-ключей (depth=2)
        suggest_results = await self._run_suggest(seed_keywords, depth=2)
        for kw in suggest_results:
            all_candidates.add(kw)
            sources.setdefault(kw, []).append("google_suggest_iter1")
        self._log(f"Google Suggest (итерация 1): {len(suggest_results)} кандидатов")

        # 1.2 Google Trends related queries
        trends_results = await self._run_trends(seed_keywords, geo)
        for kw in trends_results:
            all_candidates.add(kw)
            sources.setdefault(kw, []).append("google_trends_iter1")
        self._log(f"Google Trends (итерация 1): {len(trends_results)} кандидатов")

        # 1.3 LLM expand_keywords — long-tail и модификаторы
        llm_results = await self._run_llm_expand(seed_keywords, business_context, geo)
        for kw in llm_results:
            all_candidates.add(kw)
            sources.setdefault(kw, []).append("llm_expand_iter1")
        self._log(f"LLM expansion (итерация 1): {len(llm_results)} кандидатов")

        # 1.4 Объединяем и дедуплицируем
        iter1_candidates = sorted(all_candidates)
        self._log(f"Итог итерации 1: {len(iter1_candidates)} уникальных кандидатов")

        # ===================== ИТЕРАЦИЯ 2 =====================
        self._log("--- Итерация 2 ---")

        # Берём top-10 новых ключей из итерации 1
        new_keywords = [kw for kw in iter1_candidates if kw not in seed_keywords]
        top_new = new_keywords[:10]
        self._log(f"Top-10 новых ключей для второй итерации: {len(top_new)}")

        if top_new:
            # 2.1 Google Suggest для top-10 новых ключей
            suggest_results_2 = await self._run_suggest(top_new, depth=1)
            for kw in suggest_results_2:
                all_candidates.add(kw)
                sources.setdefault(kw, []).append("google_suggest_iter2")
            self._log(f"Google Suggest (итерация 2): {len(suggest_results_2)} кандидатов")

            # 2.2 LLM expand для top-10
            llm_results_2 = await self._run_llm_expand(top_new, business_context, geo)
            for kw in llm_results_2:
                all_candidates.add(kw)
                sources.setdefault(kw, []).append("llm_expand_iter2")
            self._log(f"LLM expansion (итерация 2): {len(llm_results_2)} кандидатов")
        else:
            self._log("Нет новых ключей для второй итерации, пропускаем")

        # ===================== ФИНАЛЬНАЯ ДЕДУПЛИКАЦИЯ =====================
        final_candidates = sorted(all_candidates)

        # Закрываем HTTP-клиент GoogleSuggestService
        try:
            await self.suggest_service.close()
        except Exception as exc:
            self.logger.debug("[%s] Ошибка закрытия GoogleSuggestService: %s", self.name, exc)

        self._log(
            f"Расширение завершено: {len(final_candidates)} уникальных кандидатов "
            f"(из {len(seed_keywords)} seed-ключей)"
        )

        return {
            "candidates": final_candidates,
            "sources": {k: list(dict.fromkeys(v)) for k, v in sources.items()},
        }

    async def _run_suggest(self, keywords: List[str], depth: int) -> List[str]:
        """
        Получить подсказки Google Suggest для списка ключей.

        Args:
            keywords: Список ключевых слов.
            depth: Глубина расширения.

        Returns:
            Список уникальных подсказок.
        """
        if not keywords:
            return []

        try:
            results = await self.suggest_service.get_expanded_suggestions(
                seed_keywords=keywords,
                depth=depth,
            )
            return results
        except Exception as exc:
            self.logger.warning(
                "[%s] Ошибка Google Suggest: %s", self.name, exc,
            )
            return []

    async def _run_trends(self, keywords: List[str], geo: str) -> List[str]:
        """
        Получить связанные запросы из Google Trends.

        Args:
            keywords: Список ключевых слов.
            geo: Код региона.

        Returns:
            Список связанных запросов.
        """
        if not keywords:
            return []

        try:
            # TrendsService.get_related_queries — синхронный метод
            related = await asyncio.to_thread(
                self.trends_service.get_related_queries,
                keywords=keywords,
                geo=geo,
            )

            all_queries: Set[str] = set()
            for keyword, data in related.items():
                top_queries = data.get("top", [])
                rising_queries = data.get("rising", [])
                all_queries.update(top_queries)
                all_queries.update(rising_queries)

            return list(all_queries)
        except Exception as exc:
            self.logger.warning(
                "[%s] Ошибка Google Trends: %s", self.name, exc,
            )
            return []

    async def _run_llm_expand(
        self,
        keywords: List[str],
        business_context: str,
        geo: str,
    ) -> List[str]:
        """
        Расширить ключевые слова через LLM.

        Args:
            keywords: Список ключевых слов.
            business_context: Описание бизнеса.
            geo: Гео-таргетинг.

        Returns:
            Список сгенерированных ключевых фраз.
        """
        if not keywords:
            return []

        try:
            results = await self.llm_service.expand_keywords(
                seed_keywords=keywords,
                business_context=business_context,
                geo=geo,
            )
            return results
        except Exception as exc:
            self.logger.warning(
                "[%s] Ошибка LLM expand_keywords: %s", self.name, exc,
            )
            return []
