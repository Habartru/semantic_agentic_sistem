/**
 * Клиент для управления пайплайном через SSE.
 */

const AGENT_STEPS = [
    { key: 'research', name: 'Исследование', agent: 'ResearchAgent' },
    { key: 'expansion', name: 'Расширение', agent: 'ExpansionAgent' },
    { key: 'cleaning', name: 'Очистка', agent: 'CleaningAgent' },
    { key: 'intent', name: 'Интент', agent: 'IntentAgent' },
    { key: 'clustering', name: 'Кластеризация', agent: 'ClusteringAgent' },
    { key: 'mapping', name: 'Маппинг', agent: 'MappingAgent' },
    { key: 'prioritization', name: 'Приоритизация', agent: 'PrioritizationAgent' },
    { key: 'feedback', name: 'Обратная связь', agent: 'FeedbackAgent' },
];

function getStepIndex(agentName) {
    return AGENT_STEPS.findIndex(s => s.agent === agentName || s.key === agentName);
}

function updateConnectorColors() {
    const steps = document.querySelectorAll('[id^="pipeline-step-"]');
    steps.forEach((stepEl, idx) => {
        const connector = stepEl.querySelector('.pipeline-connector');
        if (!connector) return;
        const status = stepEl.dataset.status || 'wait';
        if (status === 'done' || status === 'run') {
            connector.style.background = 'var(--success)';
        } else if (status === 'err') {
            connector.style.background = 'var(--danger)';
        } else {
            connector.style.background = 'var(--border)';
        }
    });
}

function updateStepUI(stepIndex, status, detail) {
    const stepEl = document.getElementById(`pipeline-step-${stepIndex}`);
    if (!stepEl) return;

    stepEl.dataset.status = status;
    const circle = stepEl.querySelector('.pipeline-circle');
    const number = stepEl.querySelector('.pipeline-number');
    const check = stepEl.querySelector('.pipeline-check');
    const err = stepEl.querySelector('.pipeline-error');
    const spin = stepEl.querySelector('.pipeline-spin');
    const statusText = stepEl.querySelector('.pipeline-status-text');

    // Reset
    circle.classList.remove('pipeline-pulse');
    circle.style.background = '';
    circle.style.color = '';
    circle.style.border = '';
    number.classList.add('hidden');
    check.classList.add('hidden');
    err.classList.add('hidden');
    spin.classList.add('hidden');

    if (status === 'waiting') {
        circle.style.background = 'var(--gray-100)';
        circle.style.color = 'var(--fg-3)';
        circle.style.border = '1px solid var(--border)';
        number.classList.remove('hidden');
        if (statusText) statusText.textContent = 'Ожидает';
        if (statusText) statusText.style.color = 'var(--fg-4)';
    } else if (status === 'running') {
        circle.style.background = 'var(--primary)';
        circle.style.color = '#fff';
        circle.style.border = '1px solid var(--primary)';
        circle.classList.add('pipeline-pulse');
        spin.classList.remove('hidden');
        if (statusText) statusText.textContent = 'В процессе';
        if (statusText) statusText.style.color = 'var(--primary)';
    } else if (status === 'complete') {
        circle.style.background = 'var(--success)';
        circle.style.color = '#fff';
        circle.style.border = '1px solid var(--success)';
        check.classList.remove('hidden');
        if (statusText) statusText.textContent = 'Готово';
        if (statusText) statusText.style.color = 'var(--success)';
    } else if (status === 'error') {
        circle.style.background = 'var(--danger)';
        circle.style.color = '#fff';
        circle.style.border = '1px solid var(--danger)';
        err.classList.remove('hidden');
        if (statusText) statusText.textContent = 'Ошибка';
        if (statusText) statusText.style.color = 'var(--danger)';
    }

    updateConnectorColors();
}

function initProgressUI() {
    for (let i = 0; i < AGENT_STEPS.length; i++) {
        updateStepUI(i, 'waiting');
    }
    updateConnectorColors();
}

async function startPipeline(projectId) {
    const statusEl = document.getElementById('pipeline-status');
    const progressSection = document.getElementById('progress-section');
    const resultLink = document.getElementById('result-link');
    const pipelineMeta = document.getElementById('pipeline-meta');

    if (progressSection) {
        progressSection.classList.remove('hidden');
    }
    if (statusEl) {
        statusEl.textContent = 'Запуск пайплайна';
        statusEl.style.color = 'var(--primary)';
    }
    if (resultLink) {
        resultLink.classList.add('hidden');
    }

    // Сброс UI
    initProgressUI();

    let runId;
    try {
        const resp = await fetch(`/api/projects/${projectId}/run`, { method: 'POST' });
        if (!resp.ok) {
            throw new Error('Ошибка запуска: ' + resp.status);
        }
        const data = await resp.json();
        runId = data.run_id;
    } catch (err) {
        if (statusEl) {
            statusEl.textContent = 'Ошибка запуска: ' + err.message;
            statusEl.style.color = 'var(--danger)';
        }
        return;
    }

    if (statusEl) {
        statusEl.textContent = 'Пайплайн запущен';
    }
    if (pipelineMeta) {
        pipelineMeta.textContent = 'run #' + runId;
    }

    const evtSource = new EventSource(`/api/projects/${projectId}/runs/${runId}/stream`);

    evtSource.onmessage = (event) => {
        let msg;
        try {
            msg = JSON.parse(event.data);
        } catch (e) {
            console.warn('Невалидное SSE-сообщение:', event.data);
            return;
        }

        const { event: type, data } = msg;

        if (type === 'agent_start') {
            const idx = getStepIndex(data.agent);
            if (idx >= 0) {
                updateStepUI(idx, 'running', data.detail || '');
                // Отметить предыдущие как готовые
                for (let i = 0; i < idx; i++) {
                    updateStepUI(i, 'complete');
                }
            }
            if (statusEl) {
                statusEl.textContent = `Выполняется: ${data.agent}`;
                statusEl.style.color = 'var(--primary)';
            }
            if (pipelineMeta) {
                pipelineMeta.textContent = `Шаг ${Math.min(idx + 1, AGENT_STEPS.length)} из ${AGENT_STEPS.length}`;
            }
        } else if (type === 'agent_complete') {
            const idx = getStepIndex(data.agent);
            if (idx >= 0) {
                updateStepUI(idx, 'complete', data.detail || '');
            }
        } else if (type === 'progress') {
            if (statusEl && data.progress !== undefined) {
                statusEl.textContent = `Прогресс: ${data.progress}%`;
            }
        } else if (type === 'error') {
            if (statusEl) {
                statusEl.textContent = 'Ошибка: ' + (data.error || 'Неизвестная ошибка');
                statusEl.style.color = 'var(--danger)';
            }
            const currentIdx = AGENT_STEPS.findIndex(s => s.agent === data.agent);
            if (currentIdx >= 0) {
                updateStepUI(currentIdx, 'error', data.error || '');
            }
            evtSource.close();
        } else if (type === 'pipeline_complete') {
            for (let i = 0; i < AGENT_STEPS.length; i++) {
                updateStepUI(i, 'complete');
            }
            if (statusEl) {
                statusEl.textContent = 'Пайплайн завершён';
                statusEl.style.color = 'var(--success)';
            }
            if (pipelineMeta) {
                pipelineMeta.textContent = `Все ${AGENT_STEPS.length} шагов выполнены`;
            }
            const resultLinkWrapper = document.getElementById('result-link-wrapper');
            if (resultLinkWrapper) {
                resultLinkWrapper.classList.remove('hidden');
            }
            if (resultLink) {
                resultLink.href = `/projects/${projectId}/results/${runId}`;
            }
            // Авторедирект через 3 секунды
            setTimeout(() => {
                window.location.href = `/projects/${projectId}/results/${runId}`;
            }, 3000);
            evtSource.close();
        }
    };

    evtSource.onerror = (err) => {
        console.error('SSE ошибка:', err);
        if (statusEl) {
            statusEl.textContent = 'Ошибка соединения с сервером';
            statusEl.style.color = 'var(--danger)';
        }
        evtSource.close();
    };
}
