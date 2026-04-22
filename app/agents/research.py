"""
Агент исследования — ResearchAgent.

Анализирует сайт клиента и конкурентов, извлекает существующие страницы,
парсит мета-данные конкурентов и собирает seed-ключевые слова.
"""

import asyncio
from typing import Dict, Any, List

from app.agents.base import BaseAgent
from app.services.competitor import CompetitorService


class ResearchAgent(BaseAgent):
    """
    Агент исследования сайта клиента и конкурентов.

    Input:
        - site_url: URL сайта клиента
        - seed_keywords: стартовые ключевые слова
        - competitor_urls: список URL конкурентов
        - business_description: описание бизнеса
        - geo: гео-таргетинг

    Output:
        - existing_pages: список страниц клиента
        - competitor_pages: мета-данные страниц конкурентов
        - competitor_keywords: ключевые слова из Title/H1 конкурентов
        - seed_keywords: переданные seed-ключи
        - business_context: контекст бизнеса
    """

    name = "ResearchAgent"
    description = "Анализ сайта клиента и конкурентов, сбор исходных данных"

    def __init__(self):
        """Инициализация агента с сервисом анализа конкурентов."""
        super().__init__()
        self.competitor_service = CompetitorService()

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнить исследование сайта и конкурентов.

        Args:
            input_data: Входные данные с ключами site_url, seed_keywords,
                       competitor_urls, business_description, geo.

        Returns:
            Словарь с результатами исследования.
        """
        site_url = input_data.get("site_url", "")
        seed_keywords = input_data.get("seed_keywords", []) or []
        competitor_urls = input_data.get("competitor_urls", []) or []
        business_description = input_data.get("business_description", "")
        geo = input_data.get("geo", "Москва")

        self._log(f"Начало исследования: сайт={site_url}, конкуренты={len(competitor_urls)}")

        # --- 1. Парсим sitemap сайта клиента ---
        existing_pages: List[str] = []
        if site_url:
            try:
                self._log(f"Парсинг sitemap клиента: {site_url}")
                existing_pages = await self.competitor_service.parse_sitemap(site_url)
                self._log(f"Найдено {len(existing_pages)} страниц клиента")
            except Exception as exc:
                self.logger.warning(
                    "[%s] Ошибка парсинга sitemap клиента %s: %s",
                    self.name, site_url, exc,
                )
                existing_pages = []
        else:
            self._log("URL сайта клиента не указан, пропускаем парсинг")

        # --- 2. Анализ конкурентов ---
        competitor_pages: List[Dict[str, Any]] = []
        competitor_keywords: List[str] = []

        if competitor_urls:
            try:
                self._log(f"Анализ {len(competitor_urls)} конкурентов")
                analysis = await self.competitor_service.analyze_competitors(competitor_urls)
                competitor_pages = analysis.get("competitor_pages", [])
                competitor_keywords = analysis.get("discovered_categories", [])
                self._log(
                    f"Конкуренты проанализированы: "
                    f"{len(competitor_pages)} страниц, {len(competitor_keywords)} ключей"
                )
            except Exception as exc:
                self.logger.warning(
                    "[%s] Ошибка анализа конкурентов: %s", self.name, exc,
                )
                competitor_pages = []
                competitor_keywords = []
        else:
            self._log("Конкуренты не указаны, пропускаем анализ")

        # --- 3. Извлекаем ключевые слова из Title/H1 конкурентов ---
        extracted_keywords = self._extract_keywords_from_pages(competitor_pages)
        self._log(f"Извлечено {len(extracted_keywords)} ключей из мета-данных конкурентов")

        # Объединяем с seed-ключами
        all_seed_keywords = list(dict.fromkeys(seed_keywords + extracted_keywords))

        # --- 4. Формируем бизнес-контекст ---
        business_context = self._build_business_context(
            business_description, geo, competitor_keywords
        )

        # Закрываем HTTP-клиент сервиса
        try:
            await self.competitor_service.close()
        except Exception as exc:
            self.logger.debug("[%s] Ошибка закрытия CompetitorService: %s", self.name, exc)

        result = {
            "existing_pages": existing_pages,
            "competitor_pages": competitor_pages,
            "competitor_keywords": competitor_keywords,
            "seed_keywords": all_seed_keywords,
            "business_context": business_context,
        }

        self._log(
            f"Исследование завершено: "
            f"{len(existing_pages)} страниц клиента, "
            f"{len(competitor_pages)} страниц конкурентов, "
            f"{len(all_seed_keywords)} seed-ключей"
        )
        return result

    def _extract_keywords_from_pages(self, pages: List[Dict[str, Any]]) -> List[str]:
        """
        Извлечь ключевые слова из Title и H1 страниц конкурентов.

        Args:
            pages: Список словарей с мета-данными страниц.

        Returns:
            Список уникальных ключевых фраз.
        """
        keywords: set[str] = set()

        for page in pages:
            title = page.get("title", "")
            h1 = page.get("h1", "")

            # Добавляем title и h1 как потенциальные ключи
            if title and len(title) > 3:
                keywords.add(title.strip().lower())
            if h1 and len(h1) > 3:
                keywords.add(h1.strip().lower())

            # Извлекаем отдельные слова из title (простая эвристика)
            if title:
                # Убираем типичные разделители
                for delimiter in [" | ", " - ", " — ", ": ", "  "]:
                    title = title.replace(delimiter, " ")
                # Берём первую часть title — обычно это ключевая фраза
                parts = title.split(" ")
                if len(parts) >= 2:
                    phrase = " ".join(parts[:6]).strip().lower()
                    if len(phrase) > 3:
                        keywords.add(phrase)

        return list(keywords)

    def _build_business_context(
        self,
        business_description: str,
        geo: str,
        competitor_keywords: List[str],
    ) -> str:
        """
        Сформировать расширенный бизнес-контекст для последующих агентов.

        Args:
            business_description: Описание бизнеса.
            geo: Гео-таргетинг.
            competitor_keywords: Ключевые слова конкурентов.

        Returns:
            Строка с бизнес-контекстом.
        """
        context_parts = [
            f"Описание бизнеса: {business_description}",
            f"Гео-таргетинг: {geo}",
        ]

        if competitor_keywords:
            top_categories = competitor_keywords[:20]
            context_parts.append(
                f"Категории конкурентов: {', '.join(top_categories)}"
            )

        return "\n".join(context_parts)
