# SEO Agents — Система агентов коммерческого семантического ядра

## О проекте
Веб-приложение с пайплайном из 8 AI-агентов для автоматизации сбора, расширения, кластеризации и приоритизации коммерческого семантического ядра.

## Агенты
1. Research Agent — сбор данных
2. Expansion Agent — расширение семантики
3. Cleaning Agent — очистка от мусора
4. Intent Agent — определение интента
5. Clustering Agent — кластеризация
6. Mapping Agent — маппинг на страницы
7. Prioritization Agent — приоритизация
8. Feedback Agent — обратная связь

## Стек
- Python 3.11 + FastAPI
- OpenRouter API (LLM)
- SQLite
- Tailwind CSS
- Docker

## Быстрый старт

### Локально
1. `git clone ...`
2. `cd seo-agents`
3. `cp .env.example .env` — заполнить OPENROUTER_API_KEY
4. `pip install -r requirements.txt`
5. `uvicorn app.main:app --reload`
6. Открыть http://localhost:8000

### Docker
1. `cp .env.example .env` — заполнить OPENROUTER_API_KEY
2. `docker-compose up -d`
3. Открыть http://localhost:8000

### Деплой на VPS
1. Подключиться к серверу по SSH
2. Установить Docker и Docker Compose
3. `git clone ... && cd seo-agents`
4. `cp .env.example .env && nano .env` — заполнить ключи
5. `docker-compose up -d`
6. Настроить nginx:
   - `sudo cp nginx.conf /etc/nginx/sites-available/seo-agents`
   - `sudo ln -s /etc/nginx/sites-available/seo-agents /etc/nginx/sites-enabled/`
   - `sudo nginx -t && sudo systemctl reload nginx`
7. SSL через certbot:
   - `sudo certbot --nginx -d yourdomain.com`

## Как использовать
1. Создать проект (URL сайта, описание бизнеса, ключевые слова)
2. Нажать "Запустить анализ"
3. Наблюдать прогресс в реальном времени
4. Получить таблицу результатов
5. Скачать CSV

## Переменные окружения
- `OPENROUTER_API_KEY` — ключ OpenRouter (обязательно)
- `OPENROUTER_MODEL` — модель LLM (по умолчанию: anthropic/claude-sonnet-4)
- `DATABASE_URL` — путь к БД (по умолчанию: sqlite+aiosqlite:///./seo_agents.db)
