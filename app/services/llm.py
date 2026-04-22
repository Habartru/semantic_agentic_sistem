"""
Сервис для работы с LLM через OpenRouter.
Предоставляет обёртку над OpenAI SDK с retry-логикой, батчингом
и SEO-специфичными методами для обработки ключевых слов.
"""

import asyncio
import json
import logging
from typing import List, Dict, Any, Optional

from openai import AsyncOpenAI

from app.config import settings

# Настройка логирования
logger = logging.getLogger(__name__)

# Инициализация клиента OpenRouter
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.OPENROUTER_API_KEY,
)


class LLMService:
    """
    Сервис для взаимодействия с LLM через OpenRouter.

    Предоставляет методы для SEO-задач: классификация интента,
    расширение семантического ядра, очистка, кластеризация,
    маппинг на страницы и приоритизация.
    """

    def __init__(self, model: Optional[str] = None):
        """
        Инициализация сервиса.

        Args:
            model: Модель OpenRouter. Если не указана — используется OPENROUTER_MODEL из настроек.
        """
        self.model = model or settings.OPENROUTER_MODEL

    async def _call_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        json_mode: bool = False,
        max_tokens: int = 4000,
    ) -> str:
        """
        Базовый вызов чата к LLM с retry-логикой.

        Args:
            system_prompt: Системный промпт.
            user_prompt: Пользовательский промпт.
            temperature: Температура сэмплирования (0-1).
            json_mode: Если True — требовать JSON-ответ.
            max_tokens: Максимальное количество токенов в ответе.

        Returns:
            Текст ответа от LLM.

        Raises:
            RuntimeError: Если все попытки исчерпаны или произошла непредвиденная ошибка.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        last_exception: Optional[Exception] = None
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                response = await client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                if content is None:
                    raise ValueError("LLM вернул пустой content")
                return content.strip()
            except Exception as exc:
                last_exception = exc
                wait_seconds = 2 ** attempt  # экспоненциальный backoff: 2, 4, 8 сек
                logger.warning(
                    "Попытка %d/%d неудачна: %s. Повтор через %d сек.",
                    attempt,
                    max_retries,
                    exc,
                    wait_seconds,
                )
                if attempt < max_retries:
                    await asyncio.sleep(wait_seconds)

        raise RuntimeError(
            f"Не удалось получить ответ от LLM после {max_retries} попыток. "
            f"Последняя ошибка: {last_exception}"
        ) from last_exception

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> str:
        """
        Публичный базовый метод чата с LLM.

        Args:
            system_prompt: Системный промпт.
            user_prompt: Пользовательский промпт.
            temperature: Температура сэмплирования.
            json_mode: Требовать JSON-ответ.

        Returns:
            Текст ответа от LLM.
        """
        return await self._call_chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            json_mode=json_mode,
        )

    def _parse_json(self, text: str) -> Any:
        """
        Парсинг JSON из ответа LLM с обработкой распространённых ошибок.

        Args:
            text: Текст, который должен содержать JSON.

        Returns:
            Распарсенный Python-объект.

        Raises:
            ValueError: Если JSON не удалось распарсить.
        """
        # Убираем markdown-обёртку ```json ... ```
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            # Попытка найти первый валидный JSON-объект/массив в тексте
            for start_char in ("[", "{"):
                idx = cleaned.find(start_char)
                if idx != -1:
                    # Пробуем найти баланс скобок
                    try:
                        return json.loads(cleaned[idx:])
                    except json.JSONDecodeError:
                        pass
            raise ValueError(f"Не удалось распарсить JSON: {exc}")

    async def _call_chat_with_json_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_json_retries: int = 2,
    ) -> Any:
        """
        Вызов LLM с гарантированным JSON-ответом и повторными попытками при невалидном JSON.

        Args:
            system_prompt: Системный промпт.
            user_prompt: Пользовательский промпт.
            temperature: Температура сэмплирования.
            max_json_retries: Сколько дополнительных попыток сделать при невалидном JSON.

        Returns:
            Распарсенный JSON-объект.
        """
        for attempt in range(1, max_json_retries + 2):
            text = await self._call_chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                json_mode=True,
            )
            try:
                return self._parse_json(text)
            except ValueError as exc:
                logger.warning(
                    "Попытка парсинга JSON %d/%d неудачна: %s",
                    attempt,
                    max_json_retries + 1,
                    exc,
                )
                if attempt <= max_json_retries:
                    # Добавляем напоминание в промпт
                    user_prompt += (
                        "\n\nВАЖНО: Верни строго валидный JSON без пояснений, "
                        "без markdown-форматирования, без комментариев."
                    )
                    await asyncio.sleep(1)
                else:
                    raise RuntimeError(
                        f"LLM вернул невалидный JSON после {max_json_retries + 1} попыток. "
                        f"Последний ответ: {text[:500]}"
                    ) from exc
        # Недостижимый код, добавлен для типизации
        raise RuntimeError("Неожиданный выход из цикла JSON-retry")

    # ------------------------------------------------------------------
    # SEO-методы
    # ------------------------------------------------------------------

    async def classify_intent(
        self, keywords: List[str], business_context: str
    ) -> List[Dict[str, Any]]:
        """
        Классификация интента поисковых запросов.

        Обрабатывает ключевые слова батчами по 30 штук.
        Доступные интенты: commercial, transactional, informational, local,
        comparison, navigational, problem_based.

        Args:
            keywords: Список ключевых фраз.
            business_context: Описание бизнеса для контекста.

        Returns:
            Список словарей: [{keyword, intent, confidence, page_type}].
        """
        if not keywords:
            return []

        results: List[Dict[str, Any]] = []
        batch_size = 30

        system_prompt = (
            "Ты — senior SEO-эксперт с 10-летним опытом. "
            "Твоя задача — классифицировать интент поискового запроса. "
            "Интент — это реальная цель пользователя, стоящая за запросом. "
            "Один и тот же запрос может иметь разный интент в зависимости от контекста бизнеса. "
            "Верни результат строго в формате JSON-массива."
        )

        for i in range(0, len(keywords), batch_size):
            batch = keywords[i : i + batch_size]
            batch_str = "\n".join(f"- {kw}" for kw in batch)

            user_prompt = (
                f"Бизнес-контекст:\n{business_context}\n\n"
                f"Классифицируй интент следующих поисковых запросов:\n{batch_str}\n\n"
                "Доступные категории интента:\n"
                "- commercial — пользователь готов к покупке, ищет товар/услугу (купить, цена, заказать)\n"
                "- transactional — сильная покупательская мотивация, готов совершить сделку прямо сейчас\n"
                "- informational — ищет информацию, ответ на вопрос, инструкцию (как, что такое, зачем)\n"
                "- local — гео-зависимый запрос, связанный с конкретным городом/районом\n"
                "- comparison — сравнивает варианты, ищет лучший выбор (vs, лучше, отличия)\n"
                "- navigational — ищет конкретный сайт или бренд\n"
                "- problem_based — описывает проблему/боль, ищет решение (сломалось, болит, не работает)\n\n"
                "Для каждого запроса определи также рекомендуемый тип страницы:\n"
                "- category — категория товаров/услуг\n"
                "- product — карточка товара/услуги\n"
                "- article — статья/блог\n"
                "- landing — посадочная страница\n"
                "- comparison — страница сравнения\n"
                "- faq — страница FAQ\n"
                "- home — главная страница\n\n"
                "Верни строго JSON-массив без markdown, без комментариев:\n"
                '[{"keyword": "...", "intent": "...", "confidence": 0.95, "page_type": "..."}, ...]\n'
                "confidence — число от 0 до 1."
            )

            parsed = await self._call_chat_with_json_retry(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
            )

            if isinstance(parsed, list):
                results.extend(parsed)
            elif isinstance(parsed, dict) and "results" in parsed:
                results.extend(parsed["results"])
            else:
                logger.warning("Непредвиденный формат ответа при classify_intent: %s", type(parsed))

        return results

    async def expand_keywords(
        self,
        seed_keywords: List[str],
        business_context: str,
        geo: str,
    ) -> List[str]:
        """
        Расширение семантического ядра генерацией long-tail запросов.

        Args:
            seed_keywords: Список стартовых ключевых слов.
            business_context: Описание бизнеса.
            geo: Гео-таргетинг (город/регион).

        Returns:
            Список новых ключевых фраз.
        """
        if not seed_keywords:
            return []

        system_prompt = (
            "Ты — эксперт по семантическому ядру и SEO. "
            "Твоя задача — сгенерировать максимально релевантные long-tail запросы на основе seed-ключей. "
            "Запросы должны быть на русском языке, естественными, такими как их вводят реальные пользователи. "
            "Не повторяй исходные ключи. Добавляй модификаторы для уточнения интента. "
            "Верни результат строго в формате JSON-массива строк."
        )

        seeds_str = "\n".join(f"- {kw}" for kw in seed_keywords)

        user_prompt = (
            f"Бизнес-контекст:\n{business_context}\n\n"
            f"Гео-таргетинг: {geo}\n\n"
            f"Seed-ключевые слова:\n{seeds_str}\n\n"
            "Сгенерируй новые long-tail ключевые фразы, используя следующие типы модификаторов:\n"
            "1. Коммерческие — купить, цена, стоимость, заказать, недорого, со скидкой, в рассрочку\n"
            "2. Гео-модификаторы — с указанием города/района/метро (если применимо)\n"
            "3. Характеристики — по цвету, размеру, материалу, бренду, модели\n"
            "4. Назначение — для чего, кому, в каких условиях\n"
            "5. Аудитория — для новичков, профессионалов, детей, пожилых\n"
            "6. Проблемы — если что-то сломалось, не работает, нужно исправить\n"
            "7. Сравнения — лучше, дешевле, аналоги, отличия от\n"
            "8. Размеры/материалы — конкретные параметры товара\n\n"
            "Требования:\n"
            "- Фразы должны быть реалистичными и иметь поисковой спрос\n"
            "- Избегай слишком общих или бессмысленных сочетаний\n"
            "- Каждая фраза должна отражать конкретный интент\n"
            "- Не включай исходные seed-ключи в результат\n\n"
            "Верни строго JSON-массив строк без markdown, без комментариев:\n"
            '["фраза 1", "фраза 2", ...]'
        )

        parsed = await self._call_chat_with_json_retry(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7,
        )

        if isinstance(parsed, list):
            return [str(item) for item in parsed if isinstance(item, str)]
        elif isinstance(parsed, dict) and "keywords" in parsed:
            return [str(k) for k in parsed["keywords"] if isinstance(k, str)]
        else:
            logger.warning("Непредвиденный формат ответа при expand_keywords: %s", type(parsed))
            return []

    async def clean_keywords(
        self, keywords: List[str], business_context: str
    ) -> List[Dict[str, Any]]:
        """
        Очистка ключевых слов от дублей, мусора и нерелевантных запросов.

        Обрабатывает ключевые слова батчами по 50 штук.

        Args:
            keywords: Список ключевых фраз для очистки.
            business_context: Описание бизнеса для проверки релевантности.

        Returns:
            Список словарей: [{keyword, keep, reason}].
        """
        if not keywords:
            return []

        results: List[Dict[str, Any]] = []
        batch_size = 50

        system_prompt = (
            "Ты — SEO-аудитор с экспертизой в фильтрации семантического ядра. "
            "Твоя задача — проверить каждое ключевое слово на релевантность бизнесу, "
            "убрать дубли, мусор, нерелевантные и юридически рискованные запросы. "
            "Верни результат строго в формате JSON-массива."
        )

        for i in range(0, len(keywords), batch_size):
            batch = keywords[i : i + batch_size]
            batch_str = "\n".join(f"- {kw}" for kw in batch)

            user_prompt = (
                f"Бизнес-контекст:\n{business_context}\n\n"
                f"Проверь следующие ключевые слова:\n{batch_str}\n\n"
                "Критерии для удаления (keep = false):\n"
                "1. Дубли — семантически идентичные или почти идентичные фразы\n"
                "2. Мусор — бессмысленные сочетания слов, не имеющие поискового интента\n"
                "3. Нерелевантные — не связаны с бизнесом, продуктом или услугой\n"
                "4. Юридически рискованные — запросы, связанные с контрафактом, запрещёнными товарами, "
                "медицинскими утверждениями без лицензии, гарантиями результата\n"
                "5. Слишком общие — не отражают конкретный интент (например, одно слово без контекста)\n"
                "6. Нецелевые — явно относятся к совершенно другой нише или продукту\n\n"
                "Верни строго JSON-массив без markdown, без комментариев:\n"
                '[{"keyword": "...", "keep": true, "reason": "..."}, ...]\n'
                "reason — краткое обоснование решения на русском языке."
            )

            parsed = await self._call_chat_with_json_retry(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
            )

            if isinstance(parsed, list):
                results.extend(parsed)
            elif isinstance(parsed, dict) and "results" in parsed:
                results.extend(parsed["results"])
            else:
                logger.warning("Непредвиденный формат ответа при clean_keywords: %s", type(parsed))

        return results

    async def cluster_keywords(
        self, keywords_with_intents: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Кластеризация ключевых слов по поисковому интенту.

        Один кластер = один поисковый интент = одна страница.
        Учитывает, что семантически похожие фразы могут требовать разных страниц.

        Args:
            keywords_with_intents: Список словарей с ключевыми словами и их интентами.

        Returns:
            Список кластеров: [{cluster_name, main_keyword, keywords, intent, recommended_page_type}].
        """
        if not keywords_with_intents:
            return []

        system_prompt = (
            "Ты — эксперт по SEO-кластеризации. "
            "Твоя задача — сгруппировать ключевые слова так, чтобы каждый кластер отвечал "
            "одному поисковому интенту и мог быть размещён на одной странице сайта. "
            "Учитывай: семантически похожие фразы могут иметь РАЗНЫЙ интент и требовать разных страниц. "
            "Верни результат строго в формате JSON-массива."
        )

        data_str = json.dumps(keywords_with_intents, ensure_ascii=False, indent=2)

        user_prompt = (
            f"Данные ключевых слов с интентами:\n{data_str}\n\n"
            "Задача кластеризации:\n"
            "- Каждый кластер = один поисковый интент = одна страница сайта\n"
            "- Если две фразы похожи по словам, но имеют разный интент — они должны быть в разных кластерах\n"
            "- Пример: 'купить ноутбук' (commercial) и 'как выбрать ноутбук' (informational) — разные кластеры\n"
            "- Внутри кластера должны быть фразы, которые пользователь ожидает увидеть на одной странице\n"
            "- Не создавай слишком мелких кластеров (менее 2 фраз), если интент явно совпадает\n"
            "- Не объединяй в один кластер фразы с принципиально разным интентом\n\n"
            "Для каждого кластера укажи:\n"
            "- cluster_name — краткое название кластера (3-7 слов)\n"
            "- main_keyword — главная ключевая фраза кластера (самый высокий интент/спрос)\n"
            "- keywords — список всех фраз в кластере\n"
            "- intent — доминирующий интент кластера\n"
            "- recommended_page_type — рекомендуемый тип страницы\n\n"
            "Верни строго JSON-массив без markdown, без комментариев:\n"
            '[\n'
            '  {\n'
            '    "cluster_name": "...",\n'
            '    "main_keyword": "...",\n'
            '    "keywords": ["..."],\n'
            '    "intent": "...",\n'
            '    "recommended_page_type": "..."\n'
            '  }\n'
            ']'
        )

        parsed = await self._call_chat_with_json_retry(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
        )

        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict) and "clusters" in parsed:
            return parsed["clusters"]
        else:
            logger.warning("Непредвиденный формат ответа при cluster_keywords: %s", type(parsed))
            return []

    async def map_to_pages(
        self,
        clusters: List[Dict[str, Any]],
        existing_pages: List[str],
        business_context: str,
    ) -> List[Dict[str, Any]]:
        """
        Сопоставление кластеров ключевых слов со страницами сайта.

        Определяет действие для каждого кластера: create, update, merge, faq, skip.

        Args:
            clusters: Список кластеров от cluster_keywords.
            existing_pages: Список существующих URL-путей на сайте.
            business_context: Описание бизнеса.

        Returns:
            Список решений: [{cluster_name, recommended_page, action, reason}].
        """
        if not clusters:
            return []

        system_prompt = (
            "Ты — стратег по контенту и структуре сайта. "
            "Твоя задача — сопоставить кластеры ключевых слов со страницами сайта "
            "и принять решение о создании, обновлении или объединении страниц. "
            "Верни результат строго в формате JSON-массива."
        )

        clusters_str = json.dumps(clusters, ensure_ascii=False, indent=2)
        pages_str = "\n".join(f"- {page}" for page in existing_pages) if existing_pages else "Нет существующих страниц."

        user_prompt = (
            f"Бизнес-контекст:\n{business_context}\n\n"
            f"Кластеры ключевых слов:\n{clusters_str}\n\n"
            f"Существующие страницы сайта:\n{pages_str}\n\n"
            "Для каждого кластера выбери действие:\n"
            "- create — создать новую страницу (нет подходящей существующей)\n"
            "- update — обновить существующую страницу, добавив/расширив контент\n"
            "- merge — объединить с похожей существующей страницей, избежать каннибализации\n"
            "- faq — добавить вопрос в раздел FAQ (слишком узкий/специфичный интент)\n"
            "- skip — пропустить (нерелевантно, слишком низкий приоритет, дубль)\n\n"
            "Правила принятия решений:\n"
            "- Если есть близкая по смыслу существующая страница — предложи update или merge\n"
            "- Если интент уникален и не покрыт — предложи create с новым URL\n"
            "- Если кластер описывает конкретный вопрос — предложи faq\n"
            "- Если кластер дублирует уже покрытый интент — предложи skip\n"
            "- URL должен быть SEO-оптимизированным (латиница, дефисы, без спецсимволов)\n\n"
            "Верни строго JSON-массив без markdown, без комментариев:\n"
            '[\n'
            '  {\n'
            '    "cluster_name": "...",\n'
            '    "recommended_page": "/path/to/page",\n'
            '    "action": "create",\n'
            '    "reason": "..."\n'
            '  }\n'
            ']'
        )

        parsed = await self._call_chat_with_json_retry(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
        )

        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict) and "mapping" in parsed:
            return parsed["mapping"]
        else:
            logger.warning("Непредвиденный формат ответа при map_to_pages: %s", type(parsed))
            return []

    async def score_priorities(
        self,
        clusters_with_mapping: List[Dict[str, Any]],
        business_context: str,
    ) -> List[Dict[str, Any]]:
        """
        Оценка приоритетов кластеров по множеству факторов.

        Рассчитывает Priority Score по взвешенной формуле.

        Args:
            clusters_with_mapping: Список кластеров с маппингом на страницы.
            business_context: Описание бизнеса.

        Returns:
            Список оценок: [{cluster_name, scores, priority_score, priority_level}].
        """
        if not clusters_with_mapping:
            return []

        system_prompt = (
            "Ты — SEO-стратег и аналитик. "
            "Твоя задача — оценить каждый кластер ключевых слов по набору факторов "
            "и рассчитать итоговый приоритет. Оценивай объективно, опираясь на бизнес-контекст. "
            "Верни результат строго в формате JSON-массива."
        )

        data_str = json.dumps(clusters_with_mapping, ensure_ascii=False, indent=2)

        user_prompt = (
            f"Бизнес-контекст:\n{business_context}\n\n"
            f"Кластеры с маппингом:\n{data_str}\n\n"
            "Оцени каждый кластер по следующим факторам (от 0 до 100):\n"
            "1. business_value — насколько кластер важен для бизнеса (доход, конверсия, LTV)\n"
            "2. ranking_opportunity — насколько реалистично выйти в топ по этим запросам\n"
            "3. intent_match — насколько интент кластера совпадает с тем, что предлагает бизнес\n"
            "4. trend_growth — растёт ли спрос по этой теме (50 = стабильно, выше = рост)\n"
            "5. content_gap — насколько мало качественного контента у конкурентов\n"
            "6. keyword_difficulty — оценка сложности продвижения (0 = легко, 100 = очень сложно)\n"
            "7. cannibalization_risk — риск каннибализации с существующими страницами (0 = нет риска)\n\n"
            "Формула Priority Score (взвешенная сумма):\n"
            "priority_score = (\n"
            "    business_value * 0.25 +\n"
            "    ranking_opportunity * 0.20 +\n"
            "    intent_match * 0.20 +\n"
            "    trend_growth * 0.10 +\n"
            "    content_gap * 0.10 +\n"
            "    (100 - keyword_difficulty) * 0.10 +\n"
            "    (100 - cannibalization_risk) * 0.05\n"
            ")\n\n"
            "Уровни приоритета:\n"
            "- critical — priority_score >= 80\n"
            "- high — priority_score >= 60\n"
            "- medium — priority_score >= 40\n"
            "- low — priority_score < 40\n\n"
            "Верни строго JSON-массив без markdown, без комментариев:\n"
            '[\n'
            '  {\n'
            '    "cluster_name": "...",\n'
            '    "scores": {\n'
            '      "business_value": 85,\n'
            '      "ranking_opportunity": 70,\n'
            '      "intent_match": 90,\n'
            '      "trend_growth": 60,\n'
            '      "content_gap": 75,\n'
            '      "keyword_difficulty": 45,\n'
            '      "cannibalization_risk": 10\n'
            '    },\n'
            '    "priority_score": 72.5,\n'
            '    "priority_level": "high"\n'
            '  }\n'
            ']'
        )

        parsed = await self._call_chat_with_json_retry(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
        )

        if isinstance(parsed, list):
            # Дополнительно пересчитаем priority_score на стороне сервиса для надёжности
            for item in parsed:
                scores = item.get("scores", {})
                if isinstance(scores, dict):
                    try:
                        calculated = (
                            scores.get("business_value", 0) * 0.25
                            + scores.get("ranking_opportunity", 0) * 0.20
                            + scores.get("intent_match", 0) * 0.20
                            + scores.get("trend_growth", 0) * 0.10
                            + scores.get("content_gap", 0) * 0.10
                            + (100 - scores.get("keyword_difficulty", 0)) * 0.10
                            + (100 - scores.get("cannibalization_risk", 0)) * 0.05
                        )
                        item["priority_score"] = round(calculated, 2)
                        if calculated >= 80:
                            item["priority_level"] = "critical"
                        elif calculated >= 60:
                            item["priority_level"] = "high"
                        elif calculated >= 40:
                            item["priority_level"] = "medium"
                        else:
                            item["priority_level"] = "low"
                    except Exception as exc:
                        logger.warning("Ошибка пересчёта priority_score: %s", exc)
            return parsed
        elif isinstance(parsed, dict) and "priorities" in parsed:
            return parsed["priorities"]
        else:
            logger.warning("Непредвиденный формат ответа при score_priorities: %s", type(parsed))
            return []
