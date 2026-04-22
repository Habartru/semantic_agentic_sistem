"""
Агент классификации интента — IntentAgent.

Классифицирует интент каждого ключевого слова с помощью LLM.
Обрабатывает батчами для оптимизации запросов к API.
"""

from typing import Dict, Any, List

from app.agents.base import BaseAgent
from app.services.llm import LLMService


class IntentAgent(BaseAgent):
    """
    Агент классификации поискового интента.

    Input:
        - cleaned_keywords: очищенный список ключевых слов
        - business_context: описание бизнеса

    Output:
        - keywords_with_intents: список словарей {keyword, intent, confidence, page_type}
    """

    name = "IntentAgent"
    description = "Классификация интента поисковых запросов"

    def __init__(self):
        """Инициализация агента с LLM-сервисом."""
        super().__init__()
        self.llm_service = LLMService()

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнить классификацию интента для всех ключевых слов.

        Args:
            input_data: Входные данные с cleaned_keywords и business_context.

        Returns:
            Словарь с keywords_with_intents.
        """
        cleaned_keywords = input_data.get("cleaned_keywords", []) or []
        business_context = input_data.get("business_context", "")

        self._log(f"Начало классификации интента: {len(cleaned_keywords)} ключей")

        if not cleaned_keywords:
            self._log("Список ключевых слов пуст, возвращаем пустой результат")
            return {"keywords_with_intents": []}

        # --- LLM classify_intent батчами ---
        try:
            results = await self.llm_service.classify_intent(
                keywords=cleaned_keywords,
                business_context=business_context,
            )
        except Exception as exc:
            self.logger.warning(
                "[%s] Ошибка LLM classify_intent: %s. "
                "Возвращаем ключи с неопределённым интентом.",
                self.name, exc,
            )
            # Graceful degradation
            results = [
                {
                    "keyword": kw,
                    "intent": "unknown",
                    "confidence": 0.0,
                    "page_type": "article",
                }
                for kw in cleaned_keywords
            ]

        # Нормализуем результаты
        normalized = self._normalize_results(results, cleaned_keywords)

        self._log(f"Классификация завершена: {len(normalized)} ключей с интентом")
        return {"keywords_with_intents": normalized}

    def _normalize_results(
        self,
        llm_results: List[Dict[str, Any]],
        original_keywords: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Нормализовать и дополнить результаты классификации.

        Гарантирует, что для каждого ключа есть результат.

        Args:
            llm_results: Результаты от LLM.
            original_keywords: Исходный список ключей.

        Returns:
            Нормализованный список результатов.
        """
        result_by_keyword: Dict[str, Dict[str, Any]] = {}

        for item in llm_results:
            if isinstance(item, dict):
                keyword = item.get("keyword", "").strip().lower()
                if keyword:
                    result_by_keyword[keyword] = {
                        "keyword": item.get("keyword", ""),
                        "intent": item.get("intent", "unknown"),
                        "confidence": item.get("confidence", 0.0),
                        "page_type": item.get("page_type", "article"),
                    }

        normalized: List[Dict[str, Any]] = []
        for kw in original_keywords:
            kw_lower = kw.strip().lower()
            if kw_lower in result_by_keyword:
                normalized.append(result_by_keyword[kw_lower])
            else:
                # Если LLM не вернул результат для ключа — добавляем с неопределённым интентом
                normalized.append({
                    "keyword": kw,
                    "intent": "unknown",
                    "confidence": 0.0,
                    "page_type": "article",
                })
                self.logger.debug(
                    "[%s] Нет результата LLM для ключа '%s', используем значения по умолчанию",
                    self.name, kw,
                )

        return normalized
