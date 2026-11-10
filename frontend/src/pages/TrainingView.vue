<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { listTraining } from '../api/training'
import { selectableDatasetTasks, taskLabels } from '../domain'
import type { SelectableDatasetTask } from '../domain'
import { terminalTrainingStates, trainingStatusLabels } from '../types/training'
import type { TrainingConfig, TrainingOverview, TrainingTask } from '../types/training'

const emit = defineEmits<{
  open: [id: string, tab?: 'logs']
  retrain: [config: TrainingConfig]
  create: []
}>()

type StatusFilter = 'all' | TrainingTask['status']
type View = 'cards' | 'list'
type Sort = 'newest' | 'progress' | 'metric' | 'duration'

const statusFilters = Object.keys(trainingStatusLabels) as TrainingTask['status'][]
const overview = ref<TrainingOverview>()
const loading = ref(false)
const error = ref('')
const search = ref('')
const status = ref<StatusFilter>('all')
const taskType = ref<SelectableDatasetTask | 'all'>('all')
const architecture = ref('all')
const sort = ref<Sort>('newest')
const page = ref(1)
const pageSize = 6
const preferenceKey = 'inspection-workbench:training-view'
const view = ref<View>('cards')
try {
  if (localStorage.getItem(preferenceKey) === 'list') view.value = 'list'
} catch { /* The page still works when storage is unavailable. */ }

const architectures = computed(() => overview.value?.architectures ?? [])
const statusCounts = computed(() => overview.value?.statusCounts ?? {})
const taskCount = computed(() => Object.values(statusCounts.value).reduce((sum, count) => sum + count, 0))
const cpu = computed(() => overview.value?.devices[0])

const qualityMetrics = {
  detect: ['map50_95', 'mAP@50–95'],
  segment: ['maskMap50_95', 'Mask mAP@50–95'],
  obb: ['map50_95', 'mAP@50–95'],
  classify: ['top1', 'Top-1 准确率'],
} satisfies Record<SelectableDatasetTask, [string, string]>

const selectedMetric = computed(() => taskType.value === 'all' ? undefined : qualityMetrics[taskType.value])
function progress(task: TrainingTask) {
  if (task.status === 'succeeded') return 100
  return task.config.epochs > 0 ? Math.min(100, Math.max(0, task.epoch / task.config.epochs * 100)) : 0
}

const pageCount = computed(() => Math.max(1, Math.ceil((overview.value?.total ?? 0) / pageSize)))
const currentPage = computed(() => overview.value?.page ?? page.value)
const offset = computed(() => (currentPage.value - 1) * pageSize)
const visibleTasks = computed(() => overview.value?.tasks ?? [])

watch([search, status, taskType, architecture, sort], () => { page.value = 1 })
watch(taskType, type => { if (type === 'all' && sort.value === 'metric') sort.value = 'newest' })
watch(view, value => {
  try { localStorage.setItem(preferenceKey, value) } catch { /* Storage is optional. */ }
})

let request: AbortController | undefined
let refreshTimer: ReturnType<typeof setTimeout> | undefined

async function refresh() {
  clearTimeout(refreshTimer)
  request?.abort()
  request = new AbortController()
  const signal = request.signal
  loading.value = true
  error.value = ''
  try {
    const result = await listTraining({
      status: status.value, task: taskType.value, architecture: architecture.value,
      query: search.value, sort: sort.value, page: page.value, pageSize,
    }, signal)
    if (signal.aborted) return
    overview.value = result
    if (page.value > pageCount.value) page.value = pageCount.value
  } catch (reason) {
    if (!signal.aborted) error.value = reason instanceof Error ? reason.message : '读取训练任务失败。'
  } finally {
    if (!signal.aborted) {
      loading.value = false
      refreshTimer = setTimeout(refresh, 5000)
    }
  }
}

watch([search, status, taskType, architecture, sort, page], () => {
  request?.abort()
  clearTimeout(refreshTimer)
  refreshTimer = setTimeout(refresh, 200)
}, { immediate: true })
onUnmounted(() => {
  request?.abort()
  clearTimeout(refreshTimer)
})

function clearFilters() {
  search.value = ''
  status.value = 'all'
  taskType.value = 'all'
  architecture.value = 'all'
}

const dateFormat = new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : dateFormat.format(date)
}

function formatDuration(seconds?: number) {
  if (seconds === undefined) return '—'
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  if (hours > 0) return `${hours} 小时 ${minutes % 60} 分钟`
  return minutes > 0 ? `${minutes} 分钟` : `${Math.floor(seconds)} 秒`
}

function formatScore(value?: number) {
  return value !== undefined && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—'
}

function cardMetrics(task: TrainingTask) {
  const { metrics, config } = task
  if (['created', 'queued'].includes(task.status)) return [
    { label: '计划轮次', value: String(config.epochs) },
    { label: '初始学习率', value: String(config.learningRate) },
    { label: '优化器', value: config.optimizer },
  ]
  const [key, label] = qualityMetrics[config.task]
  const score = { label, value: formatScore(metrics[key]) }
  if (config.task === 'classify') return [
    score,
    { label: 'Top-5 准确率', value: formatScore(metrics.top5) },
    { label: '验证损失', value: metrics.valLoss?.toFixed(4) ?? '—' },
  ]
  return [
    score,
    { label: config.task === 'segment' ? 'Mask mAP@50' : 'mAP@50', value: formatScore(config.task === 'segment' ? metrics.maskMap50 : metrics.map50) },
    { label: '定位损失', value: metrics.boxLoss?.toFixed(4) ?? '—' },
  ]
}

function detailsLabel(task: TrainingTask) {
  if (task.status === 'running') return '实时监控'
  if (task.status === 'succeeded') return '查看结果'
  return '查看详情'
}

function canRetrain(task: TrainingTask) {
  return terminalTrainingStates.has(task.status)
}
</script>

<template>
  <section class="training-view" aria-labelledby="training-list-title">
    <header class="training-heading">
      <div>
        <h1 id="training-list-title">训练任务</h1>
        <p>管理训练队列，查看模型指标与运行进度。</p>
      </div>
      <button class="button" type="button" :disabled="loading" @click="refresh">刷新任务</button>
    </header>

    <div v-if="overview" class="training-overview" aria-label="训练统计">
      <div class="summary-card">
        <p>计算设备</p>
        <strong>{{ cpu?.name ?? '本机 CPU' }}</strong>
        <small>{{ overview.workerAvailable === false ? '训练执行器未启动' : '单任务执行' }}</small>
      </div>
      <div class="summary-card">
        <p>活跃训练任务</p>
        <strong>{{ statusCounts.running ?? 0 }}</strong><span> 运行中</span>
        <strong class="queued-total">{{ statusCounts.queued ?? 0 }}</strong><span> 排队中</span>
        <small>任务总数 {{ taskCount }} · {{ statusCounts.created ?? 0 }} 准备中</small>
      </div>
      <div class="summary-card">
        <p>平均 {{ selectedMetric?.[1] ?? '训练精度' }}</p>
        <strong>{{ formatScore(overview.averageScore) }}</strong>
        <small>{{ taskType === 'all' ? '选择任务类型查看' : `${taskLabels[taskType]} · 已完成任务` }}</small>
      </div>
      <div class="summary-card">
        <p>累计训练耗时</p>
        <strong>{{ formatDuration(overview.elapsedTotal) }}</strong>
        <small>已记录的任务耗时合计</small>
      </div>
    </div>

    <div v-if="error" class="training-error" role="alert">{{ error }}</div>
    <p v-if="loading && !overview" class="training-state" role="status">正在读取训练任务…</p>
    <template v-if="overview">
      <div class="training-filters">
        <div class="filter-row">
          <label class="training-search">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="5.5"/><path d="m15 15 4.5 4.5"/></svg>
            <input v-model="search" type="search" maxlength="120" placeholder="搜索任务、模型或数据集…" aria-label="搜索训练任务">
          </label>
          <div class="filter-group" role="group" aria-label="任务状态">
            <button type="button" :aria-pressed="status === 'all'" @click="status = 'all'">全部（{{ taskCount }}）</button>
            <button v-for="key in statusFilters" :key="key" type="button" :aria-pressed="status === key" @click="status = key">
              {{ trainingStatusLabels[key] }}（{{ statusCounts[key] ?? 0 }}）
            </button>
          </div>
        </div>
        <div class="filter-row">
          <label>任务类型
            <select v-model="taskType">
              <option value="all">全部类型</option>
              <option v-for="type in selectableDatasetTasks" :key="type" :value="type">{{ taskLabels[type] }}</option>
            </select>
          </label>
          <label>模型架构
            <select v-model="architecture">
              <option value="all">全部架构</option>
              <option v-for="item in architectures" :key="item">{{ item }}</option>
            </select>
          </label>
          <label>排序
            <select v-model="sort">
              <option value="newest">最新创建</option>
              <option value="progress">训练进度</option>
              <option v-if="selectedMetric" value="metric">{{ selectedMetric[1] }}</option>
              <option value="duration">训练耗时</option>
            </select>
          </label>
          <div class="filter-group view-toggle" role="group" aria-label="训练任务视图">
            <button type="button" :aria-pressed="view === 'cards'" @click="view = 'cards'">卡片</button>
            <button type="button" :aria-pressed="view === 'list'" @click="view = 'list'">列表</button>
          </div>
        </div>
      </div>

      <div v-if="!visibleTasks.length" class="training-state">
        <strong>{{ taskCount ? '没有符合条件的训练任务' : '暂无训练任务' }}</strong>
        <p>{{ taskCount ? '调整筛选条件，查看其他任务。' : '选择已准备好的数据集，新建训练任务。' }}</p>
        <button v-if="taskCount" class="button" type="button" @click="clearFilters">清除筛选</button>
        <button v-else class="button primary" type="button" @click="emit('create')">新建训练任务</button>
      </div>

      <div v-else-if="view === 'cards'" class="task-grid">
        <article v-for="task in visibleTasks" :key="task.id" class="task-card">
          <header class="card-header">
            <span class="task-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M4 18h16M6 15l4-5 4 2 4-6M15 6h3v3"/></svg>
            </span>
            <div class="task-title">
              <h2>{{ task.config.name }}</h2>
              <p>{{ taskLabels[task.config.task] }} · {{ task.modelName }} · {{ formatDate(task.startedAt ?? task.createdAt) }}</p>
            </div>
            <span class="task-status" :data-status="task.status">{{ trainingStatusLabels[task.status] }}</span>
          </header>
          <div class="card-body">
            <div class="dataset-line">
              <span>数据集 <strong>{{ task.datasetName }}</strong></span>
              <span v-if="task.datasetImageCount !== undefined">{{ task.datasetImageCount.toLocaleString('zh-CN') }} 张<span v-if="task.datasetClassCount !== undefined"> · {{ task.datasetClassCount }} 类</span></span>
            </div>
            <p class="task-settings">批次 {{ task.config.batchSize }} · 输入 {{ task.config.imageSize }} px</p>
            <div class="task-progress">
              <span>Epoch <strong>{{ task.epoch }} / {{ task.config.epochs }}</strong></span>
              <span v-if="task.status === 'running' && task.etaSeconds !== undefined">预计剩余 {{ formatDuration(task.etaSeconds) }}</span>
              <span v-else-if="task.elapsedSeconds !== undefined">{{ formatDuration(task.elapsedSeconds) }}</span>
              <span v-else>{{ progress(task).toFixed(1) }}%</span>
            </div>
            <progress :value="progress(task)" max="100" :class="{ complete: task.status === 'succeeded' }"
              :aria-label="`${task.config.name} 训练进度`" />
            <p v-if="task.failure || task.error" class="task-error">{{ task.failure?.summary ?? task.error }}</p>
            <dl class="task-metrics">
              <div v-for="metric in cardMetrics(task)" :key="metric.label">
                <dt>{{ metric.label }}</dt><dd>{{ metric.value }}</dd>
              </div>
            </dl>
          </div>
          <footer class="card-actions">
            <button class="button primary" type="button" @click="emit('open', task.id)">{{ detailsLabel(task) }}</button>
            <button v-if="task.status !== 'queued'" class="button" type="button" @click="emit('open', task.id, 'logs')">查看日志</button>
            <button v-if="canRetrain(task)" class="button" type="button" @click="emit('retrain', task.config)">再次训练</button>
          </footer>
        </article>
      </div>

      <div v-else class="task-table-wrap">
        <table class="task-table">
          <caption class="visually-hidden">训练任务列表</caption>
          <thead><tr><th scope="col">训练任务</th><th scope="col">数据集</th><th scope="col">状态</th><th scope="col">训练进度</th><th scope="col">主要指标</th><th scope="col">操作</th></tr></thead>
          <tbody>
            <tr v-for="task in visibleTasks" :key="task.id">
              <td><strong>{{ task.config.name }}</strong><small>{{ taskLabels[task.config.task] }} · {{ task.modelName }}</small></td>
              <td>{{ task.datasetName }}</td>
              <td><span class="task-status" :data-status="task.status">{{ trainingStatusLabels[task.status] }}</span></td>
              <td>
                <span class="task-progress">Epoch {{ task.epoch }} / {{ task.config.epochs }}</span>
                <progress :value="progress(task)" max="100" :class="{ complete: task.status === 'succeeded' }"
                  :aria-label="`${task.config.name} 训练进度`" />
              </td>
              <td>
                <strong>{{ formatScore(task.metrics[qualityMetrics[task.config.task][0]]) }}</strong>
                <small>{{ qualityMetrics[task.config.task][1] }}</small>
              </td>
              <td>
                <div class="table-actions">
                  <button class="button" type="button" @click="emit('open', task.id)">{{ detailsLabel(task) }}</button>
                  <button v-if="task.status !== 'queued'" class="button" type="button" @click="emit('open', task.id, 'logs')">查看日志</button>
                  <button v-if="canRetrain(task)" class="button" type="button" @click="emit('retrain', task.config)">再次训练</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="visibleTasks.length" class="task-pagination">
        <span>显示 {{ offset + 1 }}–{{ offset + visibleTasks.length }} 项，共 {{ overview.total }} 项</span>
        <nav aria-label="训练任务分页">
          <button class="button" type="button" :disabled="currentPage <= 1" @click="page = currentPage - 1">上一页</button>
          <span>{{ currentPage }} / {{ pageCount }}</span>
          <button class="button" type="button" :disabled="currentPage >= pageCount" @click="page = currentPage + 1">下一页</button>
        </nav>
      </div>
      <div class="training-environment">运行环境 <strong>{{ overview.engine }}</strong></div>
    </template>
  </section>
</template>

<style scoped>
.training-view { display: grid; gap: 18px; min-width: 0; }
.training-heading, .filter-row, .card-header, .dataset-line, .task-progress, .task-pagination { display: flex; align-items: center; gap: 12px; }
.training-heading, .dataset-line, .task-progress, .task-pagination { justify-content: space-between; }
.training-heading h1 { margin: 0; font-size: 23px; color: #152035; }
.training-heading p { margin: 4px 0 0; color: var(--muted); }
.training-heading .button { flex: none; }
.training-overview, .task-grid { display: grid; gap: 14px; }
.training-overview { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.task-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.summary-card, .training-filters, .training-state, .task-card, .task-table-wrap, .training-environment {
  min-width: 0;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
}
.summary-card { padding: 14px; }
.summary-card p { margin: 0 0 6px; color: var(--muted); font-size: 12px; }
.summary-card strong { color: #152035; font-size: 19px; font-variant-numeric: tabular-nums; }
.summary-card span, .summary-card small { color: var(--muted); }
.summary-card small { display: block; margin-top: 7px; overflow-wrap: anywhere; }
.queued-total { margin-left: 10px; }
progress {
  display: block; width: 100%; height: 7px; margin-top: 5px; border: 0; border-radius: 5px;
  appearance: none; overflow: hidden; background: #e8eef6; color: var(--home-accent, #245ad6);
}
progress.complete { color: #14966c; }
progress::-webkit-progress-bar { background: #e8eef6; }
progress::-webkit-progress-value { background: currentColor; border-radius: 5px; }
progress::-moz-progress-bar { background: currentColor; border-radius: 5px; }
.training-filters { display: grid; gap: 10px; padding: 12px; }
.filter-row { flex-wrap: wrap; }
.training-search {
  display: flex; align-items: center; gap: 8px; flex: 1 1 235px; min-width: 0;
  max-width: 340px; padding: 0 10px; border: 1px solid var(--line); border-radius: 6px;
}
.training-search:focus-within { border-color: var(--primary); }
.training-search input { width: 100%; min-width: 0; padding: 7px 0; border: 0; background: none; outline: none; }
.training-search svg, .task-icon svg { width: 17px; height: 17px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.7; }
.filter-group { display: flex; align-items: center; gap: 3px; flex-wrap: wrap; padding: 3px; border-radius: 7px; background: var(--soft); }
.filter-group button { padding: 5px 8px; color: var(--muted); background: none; border: 1px solid transparent; border-radius: 5px; font-size: 12px; }
.filter-group button[aria-pressed="true"] { color: #214eaa; font-weight: 650; background: var(--surface); border-color: #dce7fa; }
.filter-row label:not(.training-search) { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12px; }
.filter-row select { min-height: 30px; max-width: 170px; border: 1px solid var(--line); border-radius: 6px; padding: 3px 8px; background: var(--surface); }
.view-toggle { margin-left: auto; }
.training-state { padding: 30px 18px; text-align: center; color: var(--muted); }
.training-state strong { color: var(--text); }
.training-error, .task-error { padding: 9px 12px; color: var(--danger); background: #fff3f3; border-radius: 6px; overflow-wrap: anywhere; }
.task-card { display: flex; flex-direction: column; }
.card-header { padding: 13px 14px; align-items: flex-start; border-bottom: 1px solid var(--line); }
.task-icon { display: grid; place-items: center; flex: 0 0 34px; height: 34px; border-radius: 7px; color: #2457af; background: #edf3ff; }
.task-title { flex: 1; min-width: 0; }
.task-title h2 { margin: 0; color: #152035; font-size: 15px; overflow-wrap: anywhere; }
.task-title p { margin: 4px 0 0; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.task-status { display: inline-block; flex: none; padding: 3px 7px; border-radius: 5px; background: #f0f2f5; color: #4e5c6c; font-size: 11px; font-weight: 650; white-space: nowrap; }
.task-status[data-status="running"] { background: #e8f0ff; color: #214eaa; }
.task-status[data-status="succeeded"] { background: #e5f6ed; color: #176b45; }
.task-status[data-status="failed"] { background: #fde8e9; color: var(--danger); }
.card-body { padding: 13px 14px; flex: 1; }
.dataset-line { padding: 8px 10px; border-radius: 6px; background: var(--soft); color: var(--muted); font-size: 12px; }
.dataset-line span { min-width: 0; overflow-wrap: anywhere; }
.dataset-line span:last-child { flex-shrink: 0; }
.dataset-line strong { color: var(--text); }
.task-settings { margin: 7px 0 0; color: var(--muted); font: 12px/1.45 Consolas, "Microsoft YaHei UI", monospace; }
.task-progress { margin-top: 12px; font: 12px/1.45 Consolas, "Microsoft YaHei UI", monospace; color: var(--muted); }
.task-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; margin: 13px 0 0; }
.task-metrics div { padding: 8px; border-radius: 6px; border: 1px solid #e4eaf2; background: var(--soft); }
.task-metrics dt { font-size: 11px; color: var(--muted); overflow-wrap: anywhere; }
.task-metrics dd { margin: 4px 0 0; font: 650 15px/1.2 Consolas, monospace; overflow-wrap: anywhere; }
.card-actions, .table-actions, .task-pagination nav { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.card-actions { padding: 10px 14px; border-top: 1px solid var(--line); background: var(--soft); border-radius: 0 0 10px 10px; }
.card-actions .button, .table-actions .button, .task-pagination .button { font-size: 12px; }
.task-table-wrap { overflow-x: auto; }
.task-table { border-collapse: collapse; width: 100%; min-width: 690px; font-size: 13px; text-align: left; }
.task-table th, .task-table td { padding: 10px 12px; border-bottom: 1px solid var(--line); }
.task-table th { background: var(--soft); color: var(--muted); white-space: nowrap; }
.task-table tr:last-child td { border-bottom: 0; }
.task-table td small { display: block; margin-top: 3px; color: var(--muted); }
.task-table td:nth-child(4) { min-width: 115px; }
.task-table td .task-progress { margin-top: 0; white-space: nowrap; }
.task-pagination { flex-wrap: wrap; color: var(--muted); font-size: 12px; }
.training-environment { padding: 10px 12px; color: var(--muted); font-size: 12px; }
.training-environment strong { margin-left: 6px; color: var(--text); }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
@media (max-width: 1120px) { .training-overview { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 960px) { .task-grid { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 440px) {
  .view-toggle { margin-left: 0; }
  .task-icon { display: none; }
  .card-header, .dataset-line, .task-progress { flex-wrap: wrap; }
}
</style>
