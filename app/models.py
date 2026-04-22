"""
ORM-модели SQLAlchemy для SEO-агентов.
Описывают структуру таблиц в базе данных.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship

from app.database import Base


class Settings(Base):
    """
    Модель настроек приложения.
    Хранит ключ-значение конфигурации (API ключи, модели и т.д.).
    """
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)  # например "openrouter_api_key"
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Project(Base):
    """
    Модель проекта SEO.
    Хранит информацию о сайте, бизнесе, гео и стартовых ключах.
    """
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    site_url = Column(String(500), nullable=False)
    business_description = Column(Text, nullable=False)
    geo = Column(String(100), default="Москва")
    language = Column(String(10), default="ru")
    seed_keywords = Column(Text, default="[]")  # JSON-строка со списком ключей
    competitor_urls = Column(Text, default="[]")  # JSON-строка со списком URL конкурентов
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связь с запусками пайплайна
    pipeline_runs = relationship("PipelineRun", back_populates="project", cascade="all, delete-orphan")


class PipelineRun(Base):
    """
    Модель запуска пайплайна SEO-агентов.
    Отслеживает статус выполнения, прогресс и текущий агент.
    """
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    status = Column(String(50), default="pending")  # pending / running / completed / failed
    current_agent = Column(String(100), nullable=True)  # Имя текущего агента
    progress = Column(Integer, default=0)  # Прогресс от 0 до 100
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Связи
    project = relationship("Project", back_populates="pipeline_runs")
    keyword_results = relationship("KeywordResult", back_populates="pipeline_run", cascade="all, delete-orphan")


class KeywordResult(Base):
    """
    Модель результата обработки ключевого слова.
    Хранит кластер, интент, рекомендации и приоритет.
    """
    __tablename__ = "keyword_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("pipeline_runs.id"), nullable=False)
    keyword = Column(String(500), nullable=False)
    cluster_name = Column(String(255), nullable=False)
    intent = Column(String(100), nullable=False)
    confidence = Column(Float, default=0.0)
    recommended_page = Column(String(500), nullable=False)
    action = Column(String(50), nullable=False)  # create / update / merge / faq / skip
    priority_score = Column(Float, default=0.0)
    priority_level = Column(String(20), default="medium")  # critical / high / medium / low
    reason = Column(Text, nullable=True)

    # Связь с запуском пайплайна
    pipeline_run = relationship("PipelineRun", back_populates="keyword_results")
