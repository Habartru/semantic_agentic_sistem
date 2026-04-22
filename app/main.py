"""
Главный модуль FastAPI-приложения SEO-агентов.
Настраивает роуты, middleware, шаблоны и статические файлы.
"""

import asyncio
import csv
import io
import json
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jinja2 import PackageLoader, Environment

from app.database import init_db, get_db, AsyncSessionLocal
from app.models import Project, PipelineRun, KeywordResult, Settings as SettingsModel
from app.schemas import (
    ProjectCreate,
    ProjectResponse,
    PipelineRunResponse,
    KeywordResultResponse,
)
from app.config import get_setting
from app.agents.orchestrator import PipelineOrchestrator


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan event handler.
    Инициализирует базу данных при старте приложения.
    """
    await init_db()
    yield


# Создаём экземпляр FastAPI
app = FastAPI(
    title="SEO Agents",
    description="Платформа SEO-агентов для расширения семантического ядра",
    version="0.1.0",
    lifespan=lifespan
)

# Настройка CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение статических файлов
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Настройка Jinja2 шаблонов
templates = Environment(loader=PackageLoader("app", "templates"))


# ========== Роуты ==========

@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    """Лендинг — главная страница."""
    template = templates.get_template("landing.html")
    html = template.render(request=request)
    return HTMLResponse(content=html)


@app.get("/projects", response_class=HTMLResponse)
async def list_projects(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Страница со списком всех проектов.
    """
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    projects = result.scalars().all()

    template = templates.get_template("index.html")
    html = template.render(request=request, projects=projects)
    return HTMLResponse(content=html)


@app.post("/projects")
async def create_project(
    name: str = Form(...),
    site_url: str = Form(...),
    business_description: str = Form(...),
    geo: str = Form(default="Москва"),
    language: str = Form(default="ru"),
    seed_keywords: str = Form(default="[]"),
    competitor_urls: str = Form(default="[]"),
    db: AsyncSession = Depends(get_db)
):
    """
    Создание нового проекта через форму.
    """
    project = Project(
        name=name,
        site_url=site_url,
        business_description=business_description,
        geo=geo,
        language=language,
        seed_keywords=seed_keywords,
        competitor_urls=competitor_urls
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return RedirectResponse(url="/projects", status_code=303)


@app.get("/projects/new", response_class=HTMLResponse)
async def new_project(request: Request):
    """
    Страница создания нового проекта.
    """
    template = templates.get_template("project_new.html")
    html = template.render(request=request)
    return HTMLResponse(content=html)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(project_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Страница деталей проекта с историей запусков.
    """
    import json

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    # История запусков
    result_runs = await db.execute(
        select(PipelineRun)
        .where(PipelineRun.project_id == project_id)
        .order_by(PipelineRun.created_at.desc())
    )
    runs = result_runs.scalars().all()

    # Парсим JSON-списки для отображения
    try:
        seed_keywords_list = json.loads(project.seed_keywords or "[]")
    except Exception:
        seed_keywords_list = []
    try:
        competitor_urls_list = json.loads(project.competitor_urls or "[]")
    except Exception:
        competitor_urls_list = []

    template = templates.get_template("project.html")
    html = template.render(
        request=request,
        project=project,
        runs=runs,
        seed_keywords_list=seed_keywords_list,
        competitor_urls_list=competitor_urls_list,
    )
    return HTMLResponse(content=html)


@app.get("/projects/{project_id}/results/{run_id}", response_class=HTMLResponse)
async def project_results(
    project_id: int,
    run_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Страница результатов запуска пайплайна.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    result_run = await db.execute(
        select(PipelineRun).where(
            PipelineRun.id == run_id,
            PipelineRun.project_id == project_id,
        )
    )
    run = result_run.scalar_one_or_none()

    if run is None:
        raise HTTPException(status_code=404, detail="Запуск не найден")

    result_kw = await db.execute(
        select(KeywordResult).where(KeywordResult.run_id == run_id)
    )
    keyword_results = result_kw.scalars().all()

    template = templates.get_template("results.html")
    html = template.render(
        request=request,
        project=project,
        run=run,
        results=keyword_results,
    )
    return HTMLResponse(content=html)


# ========== API роуты для пайплайна ==========

# Хранилище активных очередей пайплайнов: run_id -> asyncio.Queue
pipeline_queues: dict[int, asyncio.Queue] = {}


async def _pipeline_background_task(project_id: int, run_id: int):
    """Фоновая задача запуска пайплайна. Пишет события в очередь."""
    async with AsyncSessionLocal() as db:
        try:
            # Получаем проект и запуск
            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()

            result_run = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
            run = result_run.scalar_one_or_none()

            if project is None or run is None:
                logger = __import__("logging").getLogger("pipeline")
                logger.error("Проект или запуск не найден: project_id=%s run_id=%s", project_id, run_id)
                queue = pipeline_queues.get(run_id)
                if queue:
                    await queue.put({
                        "event": "error",
                        "data": {"error": "Проект или запуск не найден"},
                    })
                    await queue.put(None)
                return

            orchestrator = PipelineOrchestrator(db)
            queue = pipeline_queues.get(run_id)
            if queue is None:
                queue = asyncio.Queue()
                pipeline_queues[run_id] = queue

            async for event in orchestrator.run_pipeline(project, run):
                await queue.put(event)

            # Сигнал окончания
            await queue.put(None)
        except Exception as e:
            logger = __import__("logging").getLogger("pipeline")
            logger.exception("Ошибка фоновой задачи пайплайна")
            queue = pipeline_queues.get(run_id)
            if queue:
                await queue.put({
                    "event": "error",
                    "data": {"error": str(e)},
                })
                await queue.put(None)


@app.post("/api/projects/{project_id}/run")
async def run_pipeline(project_id: int, db: AsyncSession = Depends(get_db)):
    """
    Создать новый запуск пайплайна и запустить его в фоне.
    Возвращает run_id для отслеживания прогресса.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    run = PipelineRun(
        project_id=project_id,
        status="pending",
        progress=0,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # Создаём очередь для SSE-событий
    queue = asyncio.Queue()
    pipeline_queues[run.id] = queue

    # Запускаем пайплайн в фоне
    asyncio.create_task(_pipeline_background_task(project_id, run.id))

    return {"run_id": run.id}


@app.get("/api/projects/{project_id}/runs/{run_id}/stream")
async def stream_pipeline(project_id: int, run_id: int, db: AsyncSession = Depends(get_db)):
    """
    SSE-стриминг прогресса выполнения пайплайна.
    Подключается к уже запущенному пайплайну через очередь.
    """
    result = await db.execute(
        select(PipelineRun).where(
            PipelineRun.id == run_id,
            PipelineRun.project_id == project_id,
        )
    )
    run = result.scalar_one_or_none()

    if run is None:
        raise HTTPException(status_code=404, detail="Запуск не найден")

    async def event_generator():
        queue = pipeline_queues.get(run_id)

        if queue is None:
            # Пайплайн не активен — проверяем статус
            if run.status == "completed":
                yield f"data: {json.dumps({'event': 'pipeline_complete', 'data': {}})}\n\n"
            elif run.status == "failed":
                yield f"data: {json.dumps({'event': 'error', 'data': {'error': run.error_message or 'Неизвестная ошибка'}})}\n\n"
            else:
                yield f"data: {json.dumps({'event': 'error', 'data': {'error': 'Очередь пайплайна не найдена'}})}\n\n"
            return

        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@app.get("/api/projects/{project_id}/runs/{run_id}/results")
async def get_pipeline_results(
    project_id: int,
    run_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Получить результаты запуска пайплайна — список KeywordResult.
    """
    result = await db.execute(
        select(PipelineRun).where(
            PipelineRun.id == run_id,
            PipelineRun.project_id == project_id,
        )
    )
    run = result.scalar_one_or_none()

    if run is None:
        raise HTTPException(status_code=404, detail="Запуск не найден")

    result_kw = await db.execute(
        select(KeywordResult).where(KeywordResult.run_id == run_id)
    )
    keyword_results = result_kw.scalars().all()

    return [KeywordResultResponse.from_orm(k) for k in keyword_results]


@app.get("/api/projects/{project_id}/runs/{run_id}/export/csv")
async def export_pipeline_csv(
    project_id: int,
    run_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Экспорт результатов запуска пайплайна в CSV.
    Колонки: keyword, cluster, intent, recommended_page, action, priority_score, priority_level
    """
    result = await db.execute(
        select(PipelineRun).where(
            PipelineRun.id == run_id,
            PipelineRun.project_id == project_id,
        )
    )
    run = result.scalar_one_or_none()

    if run is None:
        raise HTTPException(status_code=404, detail="Запуск не найден")

    result_kw = await db.execute(
        select(KeywordResult).where(KeywordResult.run_id == run_id)
    )
    keyword_results = result_kw.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "keyword",
        "cluster",
        "intent",
        "recommended_page",
        "action",
        "priority_score",
        "priority_level",
    ])

    for kw in keyword_results:
        writer.writerow([
            kw.keyword,
            kw.cluster_name,
            kw.intent,
            kw.recommended_page,
            kw.action,
            kw.priority_score,
            kw.priority_level,
        ])

    output.seek(0)
    content = output.read()

    return StreamingResponse(
        io.StringIO(content),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="pipeline_{run_id}_results.csv"',
        },
    )


@app.get("/api/projects/{project_id}/runs")
async def list_pipeline_runs(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Получить список всех запусков пайплайна для проекта.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    result_runs = await db.execute(
        select(PipelineRun)
        .where(PipelineRun.project_id == project_id)
        .order_by(PipelineRun.created_at.desc())
    )
    runs = result_runs.scalars().all()

    return [PipelineRunResponse.from_orm(r) for r in runs]


# ========== Роуты настроек ==========

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Страница настроек приложения.
    """
    # Получаем настройки из БД
    result = await db.execute(select(SettingsModel))
    db_settings = {s.key: s.value for s in result.scalars().all()}

    openrouter_api_key = db_settings.get("openrouter_api_key", "")
    openrouter_model = db_settings.get("openrouter_model", "")

    # Fallback на .env если в БД пусто
    if not openrouter_api_key:
        openrouter_api_key = await get_setting("openrouter_api_key", "")
    if not openrouter_model:
        openrouter_model = await get_setting("openrouter_model", "anthropic/claude-sonnet-4")

    template = templates.get_template("settings.html")
    html = template.render(
        request=request,
        openrouter_api_key=openrouter_api_key,
        openrouter_model=openrouter_model,
    )
    return HTMLResponse(content=html)


@app.post("/settings")
async def save_settings(
    request: Request,
    openrouter_api_key: str = Form(default=""),
    openrouter_model: str = Form(default="anthropic/claude-sonnet-4"),
    db: AsyncSession = Depends(get_db),
):
    """
    Сохранение настроек в базу данных.
    """
    keys_to_save = {
        "openrouter_api_key": openrouter_api_key.strip(),
        "openrouter_model": openrouter_model.strip(),
    }

    for key, value in keys_to_save.items():
        result = await db.execute(select(SettingsModel).where(SettingsModel.key == key))
        row = result.scalar_one_or_none()
        if row is not None:
            if value:
                row.value = value
            else:
                await db.delete(row)
        elif value:
            db.add(SettingsModel(key=key, value=value))

    await db.commit()
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/api/settings/test-connection")
async def test_openrouter_connection():
    """
    Тестовый запрос к OpenRouter для проверки API-ключа.
    """
    api_key = await get_setting("openrouter_api_key", "")
    if not api_key:
        return {"success": False, "message": "API ключ не задан"}

    model = await get_setting("openrouter_model", "anthropic/claude-sonnet-4")

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'OK' and nothing else."},
            ],
            max_tokens=10,
            temperature=0,
        )
        content = response.choices[0].message.content
        if content:
            return {"success": True, "message": f"Подключение успешно. Ответ: {content.strip()}"}
        return {"success": False, "message": "Пустой ответ от API"}
    except Exception as e:
        return {"success": False, "message": f"Ошибка: {str(e)}"}
