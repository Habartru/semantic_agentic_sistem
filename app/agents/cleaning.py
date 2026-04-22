"""
Агент очистки ключевых слов — CleaningAgent.

Удаляет дубли, мусор, нерелевантные и слишком короткие запросы.
Сначала программная фильтрация, затем LLM-проверка релевантности.
"""

from typing import Dict, Any, List

from app.agents.base import BaseAgent
from app.services.llm import LLMService


class CleaningAgent(BaseAgent):
    """
    Агент очистки семантического ядра.

    Input:
        - candidates: список кандидатов
        - business_context: описание бизнеса для проверки релевантности

    Output:
        - cleaned_keywords: очищенный список
        - removed: список удалённых с причинами
        - stats: статистика обработки
    """

    name = "CleaningAgent"
    description = "Очистка и фильтрация ключевых слов"

    def __init__(self):
        """Инициализация агента с LLM-сервисом."""
        super().__init__()
        self.llm_service = LLMService()

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнить очистку ключевых слов.

        Args:
            input_data: Входные данные с candidates и business_context.

        Returns:
            Словарь с cleaned_keywords, removed и stats.
        """
        candidates = input_data.get("candidates", []) or []
        business_context = input_data.get("business_context", "")

        self._log(f"Начало очистки: {len(candidates)} кандидатов")

        total_start = len(candidates)

        # --- Шаг 1: Программная дедупликация ---
        self._log("Шаг 1: Программная дедупликация")
        deduped = self._deduplicate(candidates)
        self._log(f"После дедупликации: {len(deduped)} (удалено {total_start - len(deduped)})")

        # --- Шаг 2: Удаление слишком коротких ---
        self._log("Шаг 2: Фильтрация по длине")
        long_enough = [kw for kw in deduped if len(kw.strip()) >= 3]
        removed_short = [
            {"keyword": kw, "reason": "Слишком короткий запрос (< 3 символов)"}
            for kw in deduped if len(kw.strip()) < 3
        ]
        self._log(f"После фильтрации длины: {len(long_enough)} (удалено {len(removed_short)})")

        # --- Шаг 3: LLM clean_keywords батчами ---
        self._log("Шаг 3: LLM-проверка релевантности")
        llm_cleaned, removed_by_llm = await self._run_llm_clean(
            long_enough, business_context
        )
        self._log(
            f"После LLM-очистки: {len(llm_cleaned)} (удалено {len(removed_by_llm)})"
        )

        # --- Собираем статистику ---
        removed = removed_short + removed_by_llm
        kept = len(llm_cleaned)
        removed_total = len(removed)

        stats = {
            "total": total_start,
            "kept": kept,
            "removed": removed_total,
            "deduped": total_start - len(deduped),
            "too_short": len(removed_short),
            "llm_rejected": len(removed_by_llm),
        }

        self._log(
            f"Очистка завершена: {kept} из {total_start} сохранено "
            f"({removed_total} удалено)"
        )

        return {
            "cleaned_keywords": llm_cleaned,
            "removed": removed,
            "stats": stats,
        }

    def _deduplicate(self, keywords: List[str]) -> List[str]:
        """
        Программная дедупликация: lowercase, strip, уникальные.

        Args:
            keywords: Список ключевых слов.

        Returns:
            Список уникальных ключевых слов с сохранением порядка.
        """
        seen: set[str] = set()
        result: List[str] = []

        for kw in keywords:
            normalized = kw.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)

        return result

    async def _run_llm_clean(
        self,
        keywords: List[str],
        business_context: str,
    ) -> tuple[List[str], List[Dict[str, str]]]:
        """
        Выполнить LLM-очистку ключевых слов батчами.

        Args:
            keywords: Список ключевых слов.
            business_context: Описание бизнеса.

        Returns:
            Кортеж (сохранённые ключи, удалённые с причинами).
        """
        if not keywords:
            return [], []

        try:
            llm_results = await self.llm_service.clean_keywords(
                keywords=keywords,
                business_context=business_context,
            )
        except Exception as exc:
            self.logger.warning(
                "[%s] Ошибка LLM clean_keywords: %s. "
                "Возвращаем все ключи без LLM-фильтрации.",
                self.name, exc,
            )
            # Graceful degradation: если LLM недоступен — возвращаем всё как есть
            return keywords, []

        kept: List[str] = []
        removed: List[Dict[str, str]] = []

        for item in llm_results:
            if isinstance(item, dict):
                keyword = item.get("keyword", "")
                keep = item.get("keep", True)
                reason = item.get("reason", "")

                if keep:
                    kept.append(keyword)
                else:
                    removed.append({
                        "keyword": keyword,
                        "reason": reason or "Удалено по решению LLM",
                    })
            else:
                # Если формат неожиданный — просто пропускаем
                self.logger.debug(
                    "[%s] Неожиданный формат элемента LLM: %s", self.name, item,
                )

        return kept, removed
