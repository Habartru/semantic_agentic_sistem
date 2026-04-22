"""
Оркестратор пайплайна SEO-агентов — PipelineOrchestrator.

Управляет последовательным запуском всех агентов:
Research -> Expansion -> Cleaning -> Intent -> Clustering -> Mapping -> Prioritization -> Feedback

Yield-ит SSE-события с прогрессом выполнения.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, AsyncGenerator

from app.agents.research import ResearchAgent
from app.agents.expansion import ExpansionAgent
from app.agents.cleaning import CleaningAgent
from app.agents.intent import IntentAgent
from app.agents.clustering import ClusteringAgent
from app.agents.mapping import MappingAgent
from app.agents.prioritization import PrioritizationAgent
from app.agents.feedback import FeedbackAgent
from app.models import Project, PipelineRun, KeywordResult


logger = logging.getLogger("orchestrator")


class PipelineOrchestrator:
    """Оркестратор пайплайна SEO-агентов."""

    def __init__(self, db_session):
        self.db = db_session
        self.agents = [
            ("ResearchAgent", ResearchAgent()),
            ("ExpansionAgent", ExpansionAgent()),
            ("CleaningAgent", CleaningAgent()),
            ("IntentAgent", IntentAgent()),
            ("ClusteringAgent", ClusteringAgent()),
            ("MappingAgent", MappingAgent()),
            ("PrioritizationAgent", PrioritizationAgent()),
            ("FeedbackAgent", FeedbackAgent()),
        ]

    async def run_pipeline(
        self, project: Project, run: PipelineRun
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Запускает цепочку агентов последовательно.
        Yield-ит SSE-события прогресса.
        """
        # Подготовить начальные данные из Project
        try:
            seed_keywords = json.loads(project.seed_keywords or "[]")
        except json.JSONDecodeError:
            seed_keywords = []

        try:
            competitor_urls = json.loads(project.competitor_urls or "[]")
        except json.JSONDecodeError:
            competitor_urls = []

        input_data = {
            "site_url": project.site_url,
            "seed_keywords": seed_keywords,
            "competitor_urls": competitor_urls,
            "business_description": project.business_description,
            "geo": project.geo,
        }

        total_agents = len(self.agents)
        current_data = input_data

        # Устанавливаем время старта
        run.started_at = datetime.utcnow()
        await self.db.commit()

        for i, (agent_name, agent) in enumerate(self.agents):
            # Обновить PipelineRun в БД
            run.current_agent = agent_name
            run.progress = int((i / total_agents) * 100)
            run.status = "running"
            await self.db.commit()

            # Yield SSE event: agent started
            yield {
                "event": "agent_start",
                "data": {
                    "agent": agent_name,
                    "step": i + 1,
                    "total": total_agents,
                },
            }

            try:
                # Запустить агента
                result = await agent.run(current_data)
                current_data = {**current_data, **result}  # merge results

                # Yield SSE event: agent completed
                yield {
                    "event": "agent_complete",
                    "data": {
                        "agent": agent_name,
                        "step": i + 1,
                    },
                }

            except Exception as e:
                logger.exception("Ошибка в агенте %s", agent_name)
                # Yield SSE error
                run.status = "failed"
                run.error_message = f"Ошибка в {agent_name}: {str(e)}"
                await self.db.commit()
                yield {
                    "event": "error",
                    "data": {
                        "agent": agent_name,
                        "error": str(e),
                    },
                }
                return

        # Сохранить результаты в KeywordResult
        await self._save_results(run.id, current_data)

        # Финальные результаты для подсчёта ключевых слов
        results = current_data.get("results", [])
        total_keywords = 0
        for r in results:
            keywords = r.get("keywords", [])
            if isinstance(keywords, list):
                total_keywords += len(keywords)

        run.status = "completed"
        run.progress = 100
        run.completed_at = datetime.utcnow()
        await self.db.commit()

        yield {
            "event": "pipeline_complete",
            "data": {"total_keywords": total_keywords},
        }

    async def _save_results(self, run_id: int, data: Dict[str, Any]):
        """Сохранить финальные результаты в БД."""
        results = data.get("results", [])
        if not results:
            logger.warning("Нет результатов для сохранения в KeywordResult")
            return

        # Собираем confidence по keyword из keywords_with_intents если есть
        confidence_map: Dict[str, float] = {}
        keywords_with_intents = data.get("keywords_with_intents", [])
        for item in keywords_with_intents:
            if isinstance(item, dict):
                kw = item.get("keyword", "").strip().lower()
                if kw:
                    confidence_map[kw] = item.get("confidence", 0.0) or 0.0

        saved_count = 0
        for cluster_result in results:
            if not isinstance(cluster_result, dict):
                continue

            cluster_name = cluster_result.get("cluster_name", "Без названия")
            intent = cluster_result.get("intent", "unknown")
            recommended_page = cluster_result.get("recommended_page", "/")
            action = cluster_result.get("action", "create")
            priority_score = cluster_result.get("priority_score", 0.0) or 0.0
            priority_level = cluster_result.get("priority_level", "medium")
            reason = cluster_result.get("reason", "")

            keywords = cluster_result.get("keywords", [])
            if isinstance(keywords, str):
                keywords = [keywords]
            elif not isinstance(keywords, list):
                keywords = []

            for keyword in keywords:
                if not keyword:
                    continue
                kw_lower = str(keyword).strip().lower()
                confidence = confidence_map.get(kw_lower, 0.0)

                keyword_result = KeywordResult(
                    run_id=run_id,
                    keyword=str(keyword),
                    cluster_name=cluster_name,
                    intent=intent,
                    confidence=confidence,
                    recommended_page=recommended_page,
                    action=action,
                    priority_score=priority_score,
                    priority_level=priority_level,
                    reason=reason,
                )
                self.db.add(keyword_result)
                saved_count += 1

        await self.db.commit()
        logger.info("Сохранено %d KeywordResult для run_id=%s", saved_count, run_id)
