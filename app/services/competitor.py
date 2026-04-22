"""
Сервис анализа конкурентов.

Скачивает sitemap, парсит мета-данные страниц
и извлекает информацию о структуре сайтов конкурентов.
"""

import asyncio
import logging
import random
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from lxml import etree

logger = logging.getLogger(__name__)

# Паттерны URL, которые считаем категориями/каталогами
_CATEGORY_PATTERNS = [
    re.compile(r"/catalog", re.IGNORECASE),
    re.compile(r"/category", re.IGNORECASE),
    re.compile(r"/cat/", re.IGNORECASE),
    re.compile(r"/collections?", re.IGNORECASE),
    re.compile(r"/products?", re.IGNORECASE),
    re.compile(r"/shop", re.IGNORECASE),
    re.compile(r"/store", re.IGNORECASE),
    re.compile(r"/range", re.IGNORECASE),
    re.compile(r"/assortment", re.IGNORECASE),
]

# Паттерны URL, которые исключаем (страницы товаров, статьи и т.д.)
_EXCLUDE_PATTERNS = [
    re.compile(r"/product/[^/]+/[^/]+$"),  # глубокие товарные страницы
    re.compile(r"/item/[^/]+/[^/]+$"),
    re.compile(r"/article/[^/]+/[^/]+$"),
    re.compile(r"/blog/[^/]+/[^/]+$"),
    re.compile(r"/news/[^/]+/[^/]+$"),
]


class CompetitorService:
    """Сервис анализа конкурентов."""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; SEOBot/1.0)"
                )
            },
        )

    async def _fetch_with_retry(
        self,
        url: str,
        max_attempts: int = 3,
    ) -> Optional[httpx.Response]:
        """
        Выполнить GET-запрос с повторными попытками.

        Args:
            url: URL для запроса.
            max_attempts: Максимальное количество попыток.

        Returns:
            Объект Response или None при неудаче.
        """
        last_exception: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                logger.debug(
                    "GET %s (попытка %s/%s)",
                    url,
                    attempt,
                    max_attempts,
                )
                response = await self.client.get(url)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_exception = exc
                logger.warning(
                    "HTTP-ошибка %s для %s (попытка %s/%s)",
                    exc.response.status_code,
                    url,
                    attempt,
                    max_attempts,
                )
            except httpx.RequestError as exc:
                last_exception = exc
                logger.warning(
                    "Сетевая ошибка для %s (попытка %s/%s): %s",
                    url,
                    attempt,
                    max_attempts,
                    exc,
                )

            if attempt < max_attempts:
                delay = random.uniform(0.5, 1.5)
                await asyncio.sleep(delay)

        logger.error(
            "Не удалось загрузить %s после %s попыток: %s",
            url,
            max_attempts,
            last_exception,
        )
        return None

    async def parse_sitemap(self, site_url: str) -> list[str]:
        """
        Скачать и распарсить sitemap.xml конкурента.

        Пробует найти sitemap по нескольким путям:
        1. /sitemap.xml
        2. /sitemap_index.xml
        3. Через robots.txt (директива Sitemap:)

        Args:
            site_url: Базовый URL сайта (например, https://example.com).

        Returns:
            Список URL из sitemap, отфильтрованных по категориям.
            При ошибке возвращает пустой список.
        """
        base = site_url.rstrip("/")
        parsed_base = urlparse(base)

        # Список возможных путей к sitemap
        candidates = [
            f"{base}/sitemap.xml",
            f"{base}/sitemap_index.xml",
        ]

        # Пробуем найти sitemap в robots.txt
        robots_url = f"{base}/robots.txt"
        robots_resp = await self._fetch_with_retry(robots_url)
        if robots_resp is not None:
            for line in robots_resp.text.splitlines():
                stripped = line.strip()
                if stripped.lower().startswith("sitemap:"):
                    sitemap_url = stripped.split(":", 1)[1].strip()
                    if sitemap_url not in candidates:
                        candidates.insert(0, sitemap_url)

        all_urls: list[str] = []

        for sitemap_url in candidates:
            resp = await self._fetch_with_retry(sitemap_url)
            if resp is None:
                continue

            try:
                root = etree.fromstring(resp.content)
            except etree.XMLSyntaxError as exc:
                logger.warning(
                    "Ошибка парсинга XML %s: %s",
                    sitemap_url,
                    exc,
                )
                continue

            # Определяем пространство имён
            nsmap = root.nsmap
            ns = nsmap.get(None, "")

            if ns:
                loc_elements = root.findall(f".//{{{ns}}}loc")
            else:
                loc_elements = root.findall(".//loc")

            for elem in loc_elements:
                if elem.text:
                    all_urls.append(elem.text.strip())

            logger.info(
                "Из %s извлечено %s URL",
                sitemap_url,
                len(loc_elements),
            )

            # Если нашли sitemap-index, пробуем обработать вложенные sitemap
            # (упрощённо: просто собираем все <loc>)

            # Если нашли хоть один URL, считаем что sitemap найден
            if all_urls:
                break

        # Фильтруем URL: оставляем только похожие на категории
        category_urls = self._filter_category_urls(all_urls, base)
        logger.info(
            "После фильтрации категорий: %s URL из %s",
            len(category_urls),
            len(all_urls),
        )
        return category_urls

    def _filter_category_urls(
        self,
        urls: list[str],
        base_url: str,
    ) -> list[str]:
        """
        Отфильтровать URL, оставив только категорийные страницы.

        Args:
            urls: Список URL.
            base_url: Базовый URL сайта.

        Returns:
            Отфильтрованный список URL.
        """
        filtered: list[str] = []
        seen: set[str] = set()

        for url in urls:
            if not url or url in seen:
                continue
            seen.add(url)

            parsed = urlparse(url)
            path = parsed.path

            # Исключаем глубокие страницы (товары, статьи)
            excluded = any(p.search(path) for p in _EXCLUDE_PATTERNS)
            if excluded:
                continue

            # Включаем если похоже на категорию
            is_category = any(p.search(path) for p in _CATEGORY_PATTERNS)
            # Или если путь относительно короткий (2-3 сегмента)
            segments = [s for s in path.split("/") if s]
            short_path = 1 <= len(segments) <= 3

            if is_category or short_path:
                filtered.append(url)

        return filtered

    async def parse_page_meta(self, url: str) -> dict:
        """
        Извлечь мета-данные со страницы.

        Args:
            url: URL страницы для анализа.

        Returns:
            Словарь с полями:
            {
                "url": str,
                "title": str,
                "description": str,
                "h1": str,
                "h2s": list[str],
            }
            При ошибке поля будут пустыми.
        """
        result = {
            "url": url,
            "title": "",
            "description": "",
            "h1": "",
            "h2s": [],
        }

        resp = await self._fetch_with_retry(url)
        if resp is None:
            return result

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as exc:
            logger.warning("Ошибка парсинга HTML для %s: %s", url, exc)
            return result

        # Title
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            result["title"] = title_tag.string.strip()

        # Meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            result["description"] = meta_desc["content"].strip()

        # H1
        h1_tag = soup.find("h1")
        if h1_tag:
            result["h1"] = h1_tag.get_text(strip=True)

        # H2 (первые 5)
        h2_tags = soup.find_all("h2", limit=5)
        result["h2s"] = [tag.get_text(strip=True) for tag in h2_tags]

        logger.debug(
            "Мета-данные для %s: title=%s, h1=%s, h2s=%s",
            url,
            bool(result["title"]),
            bool(result["h1"]),
            len(result["h2s"]),
        )
        return result

    async def analyze_competitors(self, competitor_urls: list[str]) -> dict:
        """
        Полный анализ конкурентов.

        Для каждого конкурента:
        1. Скачивает sitemap и извлекает категорийные URL.
        2. Парсит мета-данные для категорийных страниц
           (максимум 20 на конкурента).

        Args:
            competitor_urls: Список базовых URL сайтов конкурентов.

        Returns:
            Словарь с результатами:
            {
                "competitor_pages": [
                    {"url": ..., "title": ..., "h1": ..., "description": ...},
                ],
                "discovered_categories": [str],
            }
        """
        competitor_pages: list[dict] = []
        discovered_categories: set[str] = set()

        for site_url in competitor_urls:
            site_url = site_url.strip()
            if not site_url:
                continue

            logger.info("Анализ конкурента: %s", site_url)

            # 1. Получаем URL из sitemap
            category_urls = await self.parse_sitemap(site_url)

            if not category_urls:
                logger.warning(
                    "Не удалось получить URL из sitemap для %s",
                    site_url,
                )
                continue

            # Ограничиваем количество страниц для анализа
            urls_to_parse = category_urls[:20]
            logger.info(
                "Будет проанализировано %s страниц из %s",
                len(urls_to_parse),
                len(category_urls),
            )

            # 2. Парсим мета-данные для каждой страницы
            for page_url in urls_to_parse:
                meta = await self.parse_page_meta(page_url)
                competitor_pages.append(meta)

                # Извлекаем категории из h1 или title
                category_name = meta["h1"] or meta["title"]
                if category_name:
                    discovered_categories.add(category_name)

                # Задержка между запросами 1-2 сек
                delay = random.uniform(1.0, 2.0)
                logger.debug(
                    "Пауза %.2f сек перед следующей страницей...",
                    delay,
                )
                await asyncio.sleep(delay)

        result = {
            "competitor_pages": competitor_pages,
            "discovered_categories": sorted(discovered_categories),
        }
        logger.info(
            "Анализ конкурентов завершён: %s страниц, %s категорий",
            len(competitor_pages),
            len(discovered_categories),
        )
        return result

    async def close(self) -> None:
        """Закрыть HTTP-клиент и освободить ресурсы."""
        await self.client.aclose()
        logger.debug("HTTP-клиент CompetitorService закрыт")
