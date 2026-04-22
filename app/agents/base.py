"""
Базовый класс для всех SEO-агентов пайплайна.

Определяет общий интерфейс: run(input_data) -> output_data.
Все агенты наследуют BaseAgent и переопределяют метод run().
"""

import logging
from typing import Dict, Any


class BaseAgent:
    """Базовый класс для всех агентов SEO-пайплайна."""

    name: str = "BaseAgent"
    description: str = "Базовый агент без реализации"

    def __init__(self):
        """Инициализация агента с логгером."""
        self.logger = logging.getLogger(f"agent.{self.name}")

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Основной метод агента — переопределяется в каждом агенте.

        Args:
            input_data: Входные данные в виде словаря.

        Returns:
            Выходные данные в виде словаря.

        Raises:
            NotImplementedError: Если метод не переопределён.
        """
        raise NotImplementedError(
            f"Агент {self.name} должен переопределить метод run()"
        )

    def _log(self, message: str):
        """
        Логирование с именем агента.

        Args:
            message: Сообщение для логирования.
        """
        self.logger.info("[%s] %s", self.name, message)
