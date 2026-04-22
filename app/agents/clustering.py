"""
Агент кластеризации — ClusteringAgent.

Группирует ключевые слова по поисковому интенту.
Один кластер = один интент = одна страница.
"""

from typing import Dict, Any, List

from app.agents.base import BaseAgent
from app.services.llm import LLMService


class ClusteringAgent(BaseAgent):
    """
    Агент кластеризации ключевых слов.

    Input:
        - keywords_with_intents: список словарей {keyword, intent, confidence, page_type}

    Output:
        - clusters: список кластеров {cluster_name, main_keyword, keywords, intent, recommended_page_type}
    """

    name = "ClusteringAgent"
    description = "Кластеризация ключевых слов по поисковому интенту"

    def __init__(self):
        """Инициализация агента с LLM-сервисом."""
        super().__init__()
        self.llm_service = LLMService()

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнить кластеризацию ключевых слов.

        Args:
            input_data: Входные данные с keywords_with_intents.

        Returns:
            Словарь с clusters.
        """
        keywords_with_intents = input_data.get("keywords_with_intents", []) or []

        self._log(f"Начало кластеризации: {len(keywords_with_intents)} ключей")

        if not keywords_with_intents:
            self._log("Нет данных для кластеризации, возвращаем пустой результат")
            return {"clusters": []}

        # --- LLM cluster_keywords ---
        try:
            clusters = await self.llm_service.cluster_keywords(
                keywords_with_intents=keywords_with_intents,
            )
        except Exception as exc:
            self.logger.warning(
                "[%s] Ошибка LLM cluster_keywords: %s. "
                "Формируем простую кластеризацию по интенту.",
                self.name, exc,
            )
            # Graceful degradation: простая кластеризация по интенту
            clusters = self._fallback_clustering(keywords_with_intents)

        # Нормализуем структуру кластеров
        normalized = self._normalize_clusters(clusters)

        total_keywords = sum(len(c.get("keywords", [])) for c in normalized)
        self._log(
            f"Кластеризация завершена: {len(normalized)} кластеров, "
            f"{total_keywords} ключей распределено"
        )

        return {"clusters": normalized}

    def _fallback_clustering(
        self,
        keywords_with_intents: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Резервная кластеризация по интенту (без LLM).

        Args:
            keywords_with_intents: Список ключей с интентами.

        Returns:
            Список кластеров.
        """
        from collections import defaultdict

        groups: Dict[str, List[str]] = defaultdict(list)
        for item in keywords_with_intents:
            intent = item.get("intent", "unknown")
            keyword = item.get("keyword", "")
            if keyword:
                groups[intent].append(keyword)

        clusters: List[Dict[str, Any]] = []
        for intent, keywords in groups.items():
            if not keywords:
                continue
            clusters.append({
                "cluster_name": f"Кластер {intent}",
                "main_keyword": keywords[0],
                "keywords": keywords,
                "intent": intent,
                "recommended_page_type": "article",
            })

        return clusters

    def _normalize_clusters(self, clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Нормализовать структуру кластеров.

        Args:
            clusters: Сырые данные кластеров от LLM.

        Returns:
            Нормализованный список кластеров.
        """
        normalized: List[Dict[str, Any]] = []

        for item in clusters:
            if not isinstance(item, dict):
                continue

            keywords = item.get("keywords", [])
            if isinstance(keywords, str):
                keywords = [keywords]
            elif not isinstance(keywords, list):
                keywords = []

            normalized.append({
                "cluster_name": item.get("cluster_name", "Без названия"),
                "main_keyword": item.get("main_keyword", ""),
                "keywords": [str(k) for k in keywords if k],
                "intent": item.get("intent", "unknown"),
                "recommended_page_type": item.get("recommended_page_type", "article"),
            })

        return normalized
