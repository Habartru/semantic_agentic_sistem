"""
Агент обратной связи — FeedbackAgent (заглушка).

Передаёт данные дальше по пайплайну.
В будущей версии будет отслеживать позиции после публикации контента.
"""

from typing import Dict, Any

from app.agents.base import BaseAgent


class FeedbackAgent(BaseAgent):
    """
    Агент обратной связи (заглушка для будущей версии).

    Input:
        - results: результаты приоритизации

    Output:
        - results: те же результаты
        - feedback_status: статус обратной связи
        - message: сообщение о доступности в следующей версии
    """

    name = "FeedbackAgent"
    description = "Мониторинг позиций после публикации (заглушка)"

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Передать данные дальше с метаинформацией.

        Args:
            input_data: Входные данные с results.

        Returns:
            Словарь с results, feedback_status и message.
        """
        results = input_data.get("results", []) or []

        self._log(f"Получено {len(results)} результатов для обратной связи")
        self._log("Мониторинг позиций будет доступен в следующей версии")

        return {
            "results": results,
            "feedback_status": "not_available",
            "message": "Мониторинг после публикации будет доступен в следующей версии",
        }
