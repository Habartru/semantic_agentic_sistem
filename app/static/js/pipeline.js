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

function updateStepUI(stepIndex, status, detail) {
    const stepEl = document.getElementById(`step-${stepIndex}`);
    if (!stepEl) return;

    const iconEl = stepEl.querySelector('.step-icon');
    const labelEl = stepEl.querySelector('.step-label');
    const detailEl = stepEl.querySelector('.step-detail');

    stepEl.classList.remove('opacity-50', 'bg-white', 'bg-green-50', 'bg-red-50', 'ring-2', 'ring-indigo-500');
    iconEl.classList.remove('text-gray-400', 'text-indigo-600', 'text-green-600', 'text-red-600', 'animate-pulse');

    if (status === 'waiting') {
        stepEl.classList.add('opacity-50', 'bg-white');
        iconEl.classList.add('text-gray-400');
        iconEl.innerHTML = `<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="2"/></svg>`;
    } else if (status === 'running') {
        stepEl.classList.add('bg-white', 'ring-2', 'ring-indigo-500');
        iconEl.classList.add('text-indigo-600', 'animate-pulse');
        iconEl.innerHTML = `<svg class="w-6 h-6 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>`;
    } else if (status === 'complete') {
        stepEl.classList.add('bg-green-50');
        iconEl.classList.add('text-green-600');
        iconEl.innerHTML = `<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>`;
    } else if (status === 'error') {
        stepEl.classList.add('bg-red-50');
        iconEl.classList.add('text-red-600');
        iconEl.innerHTML = `<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>`;
    }

    if (detailEl) detailEl.textContent = detail || '';
}

function initProgressUI(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';

    AGENT_STEPS.forEach((step, idx) => {
        const stepDiv = document.createElement('div');
        stepDiv.id = `step-${idx}`;
        stepDiv.className = 'flex items-center space-x-3 p-3 rounded-lg transition opacity-50 bg-white';
        stepDiv.innerHTML = `
            <div class="step-icon text-gray-400 flex-shrink-0">
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="2"/></svg>
            </div>
            <div class="flex-1 min-w-0">
                <p class="step-label text-sm font-medium text-gray-900">${step.name}</p>
                <p class="step-detail text-xs text-gray-500 truncate"></p>
            </div>
        `;
        container.appendChild(stepDiv);
    });
}

async function startPipeline(projectId) {
    const statusEl = document.getElementById('pipeline-status');
    const progressSection = document.getElementById('progress-section');
    const resultLink = document.getElementById('result-link');

    if (progressSection) {
        progressSection.classList.remove('hidden');
    }
    if (statusEl) {
        statusEl.textContent = 'Запуск пайплайна...';
        statusEl.className = 'text-sm text-indigo-600 font-medium';
    }
    if (resultLink) {
        resultLink.classList.add('hidden');
    }

    // Сброс UI
    initProgressUI('progress-steps');

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
            statusEl.className = 'text-sm text-red-600 font-medium';
        }
        return;
    }

    if (statusEl) {
        statusEl.textContent = 'Пайплайн запущен (run #' + runId + '). Ожидание событий...';
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
                statusEl.className = 'text-sm text-red-600 font-medium';
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
                statusEl.textContent = 'Пайплайн завершён!';
                statusEl.className = 'text-sm text-green-600 font-medium';
            }
            if (resultLink) {
                resultLink.href = `/projects/${projectId}/results/${runId}`;
                resultLink.classList.remove('hidden');
            }
            evtSource.close();
        }
    };

    evtSource.onerror = (err) => {
        console.error('SSE ошибка:', err);
        if (statusEl) {
            statusEl.textContent = 'Ошибка соединения с сервером';
            statusEl.className = 'text-sm text-red-600 font-medium';
        }
        evtSource.close();
    };
}
