"""
Агент маппинга на страницы — MappingAgent.

Сопоставляет кластеры ключевых слов с существующими страницами сайта.
Определяет действие: create, update, merge, faq, skip.
"""

from typing import Dict, Any, List

from app.agents.base import BaseAgent
from app.services.llm import LLMService


class MappingAgent(BaseAgent):
    """
    Агент сопоставления кластеров со страницами сайта.

    Input:
        - clusters: список кластеров
        - existing_pages: список существующих URL
        - business_context: описание бизнеса

    Output:
        - mappings: список решений {cluster_name, main_keyword, keywords, intent, recommended_page, action, reason}
    """

    name = "MappingAgent"
    description = "Сопоставление кластеров со страницами сайта"

    def __init__(self):
        """Инициализация агента с LLM-сервисом."""
        super().__init__()
        self.llm_service = LLMService()

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнить маппинг кластеров на страницы.

        Args:
            input_data: Входные данные с clusters, existing_pages, business_context.

        Returns:
            Словарь с mappings.
        """
        clusters = input_data.get("clusters", []) or []
        existing_pages = input_data.get("existing_pages", []) or []
        business_context = input_data.get("business_context", "")

        self._log(f"Начало маппинга: {len(clusters)} кластеров, {len(existing_pages)} страниц")

        if not clusters:
            self._log("Нет кластеров для маппинга, возвращаем пустой результат")
            return {"mappings": []}

        # --- LLM map_to_pages ---
        try:
            mapping_results = await self.llm_service.map_to_pages(
                clusters=clusters,
                existing_pages=existing_pages,
                business_context=business_context,
            )
        except Exception as exc:
            self.logger.warning(
                "[%s] Ошибка LLM map_to_pages: %s. "
                "Используем резервную логику маппинга.",
                self.name, exc,
            )
            # Graceful degradation
            mapping_results = self._fallback_mapping(clusters, existing_pages)

        # Обогащаем маппинг данными из кластеров
        enriched = self._enrich_mappings(mapping_results, clusters)

        # Статистика по действиям
        action_counts: Dict[str, int] = {}
        for m in enriched:
            action = m.get("action", "unknown")
            action_counts[action] = action_counts.get(action, 0) + 1

        self._log(
            f"Маппинг завершён: {len(enriched)} решений. "
            f"Действия: {action_counts}"
        )

        return {"mappings": enriched}

    def _fallback_mapping(
        self,
        clusters: List[Dict[str, Any]],
        existing_pages: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Резервный маппинг без LLM.

        Если нет существующих страниц — предлагает create для всех.
        Если есть — простое сопоставление по совпадению слов.

        Args:
            clusters: Список кластеров.
            existing_pages: Список существующих страниц.

        Returns:
            Список решений маппинга.
        """
        results: List[Dict[str, Any]] = []

        for cluster in clusters:
            cluster_name = cluster.get("cluster_name", "")
            main_keyword = cluster.get("main_keyword", "")

            # Формируем URL из main_keyword
            suggested_url = self._keyword_to_url(main_keyword)

            action = "create"
            reason = "Новая страница (резервная логика)"

            # Простое сопоставление: ищем похожие страницы
            if existing_pages:
                for page in existing_pages:
                    page_lower = page.lower()
                    if any(word in page_lower for word in main_keyword.lower().split()[:2]):
                        action = "update"
                        suggested_url = page
                        reason = f"Обновление существующей страницы {page}"
                        break

            results.append({
                "cluster_name": cluster_name,
                "recommended_page": suggested_url,
                "action": action,
                "reason": reason,
            })

        return results

    def _keyword_to_url(self, keyword: str) -> str:
        """
        Преобразовать ключевое слово в SEO-friendly URL.

        Args:
            keyword: Ключевая фраза.

        Returns:
            URL-путь.
        """
        import re
        import urllib.parse

        if not keyword:
            return "/"

        # Транслитерация (упрощённая)
        translit_map = {
            "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
            "ё": "yo", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
            "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
            "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
            "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
            "э": "e", "ю": "yu", "я": "ya",
        }

        keyword_lower = keyword.lower()
        result = []
        for ch in keyword_lower:
            if ch in translit_map:
                result.append(translit_map[ch])
            elif ch.isalnum():
                result.append(ch)
            else:
                result.append("-")

        slug = "".join(result)
        # Убираем множественные дефисы
        slug = re.sub(r"-+", "-", slug)
        slug = slug.strip("-")

        return f"/{slug}" if slug else "/"

    def _enrich_mappings(
        self,
        mapping_results: List[Dict[str, Any]],
        clusters: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Обогатить результаты маппинга данными из кластеров.

        Args:
            mapping_results: Результаты от LLM.
            clusters: Исходные кластеры.

        Returns:
            Обогащённый список маппингов.
        """
        cluster_by_name: Dict[str, Dict[str, Any]] = {}
        for c in clusters:
            name = c.get("cluster_name", "")
            if name:
                cluster_by_name[name] = c

        enriched: List[Dict[str, Any]] = []

        for m in mapping_results:
            if not isinstance(m, dict):
                continue

            cluster_name = m.get("cluster_name", "")
            cluster = cluster_by_name.get(cluster_name, {})

            enriched.append({
                "cluster_name": cluster_name,
                "main_keyword": cluster.get("main_keyword", m.get("main_keyword", "")),
                "keywords": cluster.get("keywords", []),
                "intent": cluster.get("intent", "unknown"),
                "recommended_page": m.get("recommended_page", "/"),
                "action": m.get("action", "create"),
                "reason": m.get("reason", ""),
            })

        return enriched
