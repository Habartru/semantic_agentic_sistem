"""
Pydantic-схемы для валидации данных и API-ответов.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ========== Project схемы ==========

class ProjectCreate(BaseModel):
    """Схема для создания нового проекта."""
    name: str = Field(..., min_length=1, max_length=255, description="Название проекта")
    site_url: str = Field(..., min_length=1, max_length=500, description="URL сайта")
    business_description: str = Field(..., min_length=1, description="Описание бизнеса")
    geo: str = Field(default="Москва", max_length=100, description="Гео-таргетинг")
    language: str = Field(default="ru", max_length=10, description="Язык")
    seed_keywords: str = Field(default="[]", description="JSON-строка со списком стартовых ключевых слов")
    competitor_urls: str = Field(default="[]", description="JSON-строка со списком URL конкурентов")


class ProjectResponse(BaseModel):
    """Схема ответа с данными проекта."""
    id: int
    name: str
    site_url: str
    business_description: str
    geo: str
    language: str
    seed_keywords: str
    competitor_urls: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ========== PipelineRun схемы ==========

class PipelineRunResponse(BaseModel):
    """Схема ответа с данными запуска пайплайна."""
    id: int
    project_id: int
    status: str
    current_agent: Optional[str] = None
    progress: int
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ========== KeywordResult схемы ==========

class KeywordResultResponse(BaseModel):
    """Схема ответа с результатом обработки ключевого слова."""
    id: int
    run_id: int
    keyword: str
    cluster_name: str
    intent: str
    confidence: float
    recommended_page: str
    action: str
    priority_score: float
    priority_level: str
    reason: Optional[str] = None

    class Config:
        from_attributes = True


# ========== Общие схемы ==========

class ProjectListResponse(BaseModel):
    """Схема ответа со списком проектов."""
    projects: List[ProjectResponse]


class ProjectDetailResponse(BaseModel):
    """Схема ответа с деталями проекта и его запусками."""
    project: ProjectResponse
    pipeline_runs: List[PipelineRunResponse]


class APIResponse(BaseModel):
    """Базовая схема API-ответа."""
    success: bool
    message: str
    data: Optional[dict] = None
