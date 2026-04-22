"""
Агент приоритизации — PrioritizationAgent.

Оценивает кластеры по 7 факторам, рассчитывает priority_score
и определяет уровень приоритета.
"""

from typing import Dict, Any, List

from app.agents.base import BaseAgent
from app.services.llm import LLMService


class PrioritizationAgent(BaseAgent):
    """
    Агент приоритизации кластеров ключевых слов.

    Input:
        - mappings: список маппингов
        - business_context: описание бизнеса

    Output:
        - results: список с priority_score, priority_level, reason
    """

    name = "PrioritizationAgent"
    description = "Оценка приоритетов кластеров по множеству факторов"

    def __init__(self):
        """Инициализация агента с LLM-сервисом."""
        super().__init__()
        self.llm_service = LLMService()

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнить приоритизацию кластеров.

        Args:
            input_data: Входные данные с mappings и business_context.

        Returns:
            Словарь с results.
        """
        mappings = input_data.get("mappings", []) or []
        business_context = input_data.get("business_context", "")

        self._log(f"Начало приоритизации: {len(mappings)} маппингов")

        if not mappings:
            self._log("Нет данных для приоритизации, возвращаем пустой результат")
            return {"results": []}

        # --- LLM score_priorities ---
        try:
            priority_results = await self.llm_service.score_priorities(
                clusters_with_mapping=mappings,
                business_context=business_context,
            )
        except Exception as exc:
            self.logger.warning(
                "[%s] Ошибка LLM score_priorities: %s. "
                "Используем резервную оценку приоритетов.",
                self.name, exc,
            )
            # Graceful degradation
            priority_results = self._fallback_priorities(mappings)

        # Обогащаем результаты данными из маппингов
        enriched = self._enrich_results(priority_results, mappings)

        # Статистика по уровням приоритета
        level_counts: Dict[str, int] = {}
        for r in enriched:
            level = r.get("priority_level", "unknown")
            level_counts[level] = level_counts.get(level, 0) + 1

        self._log(
            f"Приоритизация завершена: {len(enriched)} результатов. "
            f"Уровни: {level_counts}"
        )

        return {"results": enriched}

    def _fallback_priorities(
        self,
        mappings: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Резервная приоритизация без LLM.

        Оценивает на основе размера кластера и типа действия.

        Args:
            mappings: Список маппингов.

        Returns:
            Список результатов приоритизации.
        """
        results: List[Dict[str, Any]] = []

        for m in mappings:
            keywords = m.get("keywords", [])
            cluster_size = len(keywords) if isinstance(keywords, list) else 0
            action = m.get("action", "create")

            # Базовая оценка: размер кластера + действие
            base_score = min(cluster_size * 5, 50)

            if action == "create":
                base_score += 20
            elif action == "update":
                base_score += 15
            elif action == "merge":
                base_score += 10
            elif action == "faq":
                base_score += 5

            # Ограничиваем 0-100
            priority_score = max(0, min(100, base_score))

            if priority_score >= 80:
                level = "critical"
            elif priority_score >= 60:
                level = "high"
            elif priority_score >= 40:
                level = "medium"
            else:
                level = "low"

            results.append({
                "cluster_name": m.get("cluster_name", ""),
                "scores": {
                    "business_value": 50,
                    "ranking_opportunity": 50,
                    "intent_match": 50,
                    "trend_growth": 50,
                    "content_gap": 50,
                    "keyword_difficulty": 50,
                    "cannibalization_risk": 0,
                },
                "priority_score": round(priority_score, 2),
                "priority_level": level,
            })

        return results

    def _enrich_results(
        self,
        priority_results: List[Dict[str, Any]],
        mappings: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Обогатить результаты приоритизации данными из маппингов.

        Args:
            priority_results: Результаты от LLM.
            mappings: Исходные маппинги.

        Returns:
            Обогащённый список результатов.
        """
        mapping_by_name: Dict[str, Dict[str, Any]] = {}
        for m in mappings:
            name = m.get("cluster_name", "")
            if name:
                mapping_by_name[name] = m

        enriched: List[Dict[str, Any]] = []

        for p in priority_results:
            if not isinstance(p, dict):
                continue

            cluster_name = p.get("cluster_name", "")
            mapping = mapping_by_name.get(cluster_name, {})

            # Рассчитываем priority_score если его нет
            scores = p.get("scores", {})
            priority_score = p.get("priority_score", 0)

            if not priority_score and isinstance(scores, dict):
                try:
                    priority_score = (
                        scores.get("business_value", 0) * 0.25
                        + scores.get("ranking_opportunity", 0) * 0.20
                        + scores.get("intent_match", 0) * 0.20
                        + scores.get("trend_growth", 0) * 0.10
                        + scores.get("content_gap", 0) * 0.10
                        + (100 - scores.get("keyword_difficulty", 0)) * 0.10
                        + (100 - scores.get("cannibalization_risk", 0)) * 0.05
                    )
                    priority_score = round(priority_score, 2)
                except Exception as exc:
                    self.logger.debug(
                        "[%s] Ошибка расчёта priority_score: %s", self.name, exc,
                    )
                    priority_score = 0

            # Определяем уровень приоритета
            if priority_score >= 80:
                level = "critical"
            elif priority_score >= 60:
                level = "high"
            elif priority_score >= 40:
                level = "medium"
            else:
                level = "low"

            enriched.append({
                "cluster_name": cluster_name,
                "main_keyword": mapping.get("main_keyword", p.get("main_keyword", "")),
                "keywords": mapping.get("keywords", p.get("keywords", [])),
                "intent": mapping.get("intent", "unknown"),
                "recommended_page": mapping.get("recommended_page", "/"),
                "action": mapping.get("action", "create"),
                "priority_score": priority_score,
                "priority_level": level,
                "reason": mapping.get("reason", p.get("reason", "")),
                "scores": scores if isinstance(scores, dict) else {},
            })

        # Сортируем по priority_score убыванию
        enriched.sort(key=lambda x: x.get("priority_score", 0), reverse=True)

        return enriched
