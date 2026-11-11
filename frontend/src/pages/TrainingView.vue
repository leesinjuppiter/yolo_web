<script setup lang="ts">
import { computed, onActivated, onDeactivated, onUnmounted, ref, watch } from 'vue'
import { refreshOnChanges } from '../api/changes'
import { listTraining } from '../api/training'
import DeleteTrainingButton from '../components/training/DeleteTrainingButton.vue'
import CpuBrandIcon from '../components/training/CpuBrandIcon.vue'
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
const cpu = computed(() => overview.value?.devices.find(device => device.kind === 'cpu'))
const gpus = computed(() => overview.value?.devices.filter(device => device.kind === 'cuda') ?? [])
const runningTask = computed(() => visibleTasks.value.find(task => task.status === 'running'))
const workerReady = computed(() => overview.value?.workerAvailable === true && overview.value?.workerStatus?.state === 'live')
const environmentVersions = computed(() => {
  const versions = overview.value?.workerStatus?.versions
  return [versions?.cuda ? `CUDA ${versions.cuda}` : '', versions?.torch ? `PyTorch ${versions.torch}` : ''].filter(Boolean).join(' · ')
})
const elapsedDisplay = computed(() => {
  const seconds = overview.value?.elapsedTotal
  if (seconds == null || !Number.isFinite(seconds)) return { value: '—', unit: '' }
  if (seconds >= 3600) return { value: (seconds / 3600).toFixed(1), unit: '小时' }
  return seconds >= 60 ? { value: String(Math.floor(seconds / 60)), unit: '分钟' }
    : { value: String(Math.floor(seconds)), unit: '秒' }
})

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
let active = false
let unsubscribe: (() => void) | undefined

function stopRefresh() {
  clearTimeout(refreshTimer)
  request?.abort()
  loading.value = false
}

async function refresh(quiet = false) {
  if (!active) return
  clearTimeout(refreshTimer)
  request?.abort()
  request = new AbortController()
  const signal = request.signal
  loading.value = !quiet || !overview.value
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
    if (!signal.aborted && active) {
      loading.value = false
    }
  }
}

watch([search, status, taskType, architecture, sort, page], () => {
  if (!active) return
  stopRefresh()
  refreshTimer = setTimeout(refresh, 200)
})
onActivated(() => {
  active = true
  unsubscribe = refreshOnChanges(['training', 'models', 'worker'], () => refresh(true), change => change.table !== 'training_logs' && change.table !== 'training_metrics')
  void refresh()
})
onDeactivated(() => {
  active = false
  unsubscribe?.()
  stopRefresh()
})
onUnmounted(() => { unsubscribe?.(); stopRefresh() })

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
      <button class="button" type="button" :disabled="loading" @click="refresh()">刷新任务</button>
    </header>

    <div v-if="overview" class="training-overview" aria-label="训练统计">
      <article class="summary-card compute-summary">
        <header class="summary-header">
          <h2><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="1"/><path d="M9 9h6v6H9zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg>计算设备</h2>
          <span class="summary-badge" :data-ready="workerReady">{{ workerReady ? '在线 · 就绪' : '执行器未就绪' }}</span>
        </header>
        <div class="summary-content">
          <div class="device-row"><CpuBrandIcon :vendor="cpu?.vendor"/><strong>{{ cpu?.name ?? 'CPU 型号待采集' }}</strong></div>
          <div v-for="gpu in gpus" :key="gpu.id" class="device-row"><span class="gpu-symbol" aria-hidden="true">GPU</span><strong>{{ gpu.name }}</strong><small v-if="gpu.memoryBytes != null">{{ (gpu.memoryBytes / 1024 ** 3).toFixed(1) }} GiB</small></div>
          <p v-if="!gpus.length" class="summary-description">{{ overview.workerStatus?.state === 'live' ? '当前执行环境仅提供 CPU 训练' : '等待执行器发布 GPU 信息' }}</p>
          <dl class="summary-details">
            <div><dt>CPU 架构</dt><dd>{{ cpu?.architecture ?? '—' }}</dd></div>
            <div><dt>调度方式</dt><dd>单任务执行</dd></div>
          </dl>
        </div>
        <footer class="summary-footer environment-versions" :title="environmentVersions">{{ environmentVersions || '训练环境版本待采集' }}</footer>
      </article>
      <article class="summary-card activity-summary">
        <header class="summary-header">
          <h2><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6a8 8 0 0 0-13 6M6 18a8 8 0 0 0 13-6M18 2v4h-4M6 22v-4h4"/><circle cx="12" cy="12" r="3"/></svg>活跃训练任务</h2>
          <span class="summary-badge">任务总数 {{ taskCount }}</span>
        </header>
        <div class="summary-content">
          <div class="activity-counts"><div><strong>{{ statusCounts.running ?? 0 }}</strong><span>运行中</span></div><i aria-hidden="true">/</i><div><b>{{ statusCounts.queued ?? 0 }}</b><span>排队中</span></div><i aria-hidden="true">/</i><div><b>{{ statusCounts.created ?? 0 }}</b><span>准备中</span></div></div>
          <div class="active-task-preview">
            <template v-if="runningTask"><div><strong :title="runningTask.config.name">{{ runningTask.config.name }}</strong><span>Epoch {{ runningTask.epoch }}/{{ runningTask.config.epochs }}</span></div><progress :value="progress(runningTask)" max="100" aria-label="活跃训练任务进度"/></template>
            <span v-else>{{ statusCounts.running ? '训练任务运行中，详见训练中列表' : '当前无运行中的训练任务' }}</span>
          </div>
          <div class="scheduler-slot"><span>调度槽位</span><strong>{{ statusCounts.running ?? 0 }} / 1 占用</strong><span class="slot-indicator" :data-busy="!!statusCounts.running" aria-hidden="true"/></div>
        </div>
        <footer class="summary-footer"><span>已完成 {{ statusCounts.succeeded ?? 0 }} · 已取消 {{ statusCounts.canceled ?? 0 }} · 失败 {{ statusCounts.failed ?? 0 }}</span></footer>
      </article>
      <article class="summary-card comparison-summary">
        <header class="summary-header">
          <h2><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h8M4 12h8M4 18h8m3-13 2 2 4-4m-6 8 6 6m0-6-6 6"/></svg>评估比较口径</h2>
          <span class="summary-badge">比较前核对</span>
        </header>
        <div class="summary-content">
          <strong class="comparison-title">同条件比较</strong>
          <p class="summary-description">比较前需核对验证数据、类别映射与评估参数。</p>
          <div class="comparison-checks"><span>验证数据与划分</span><span>类别与索引映射</span><span>评估参数</span></div>
        </div>
        <footer class="summary-footer">不汇总跨数据集平均精度</footer>
      </article>
      <article class="summary-card elapsed-summary">
        <header class="summary-header">
          <h2><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/></svg>累计训练耗时</h2>
          <span class="summary-badge">全部记录</span>
        </header>
        <div class="summary-content">
          <div class="elapsed-value"><strong>{{ elapsedDisplay.value }}</strong><span>{{ elapsedDisplay.unit }}</span></div>
          <p class="summary-description">已记录的任务耗时合计</p>
          <dl class="summary-details"><div><dt>累计时长</dt><dd>{{ formatDuration(overview.elapsedTotal) }}</dd></div><div><dt>已完成任务</dt><dd>{{ statusCounts.succeeded ?? 0 }} 项</dd></div></dl>
        </div>
        <footer class="summary-footer">统计范围：全部已记录任务</footer>
      </article>
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
            <button v-if="canRetrain(task)" class="button" type="button" @click="emit('retrain', task.config)">复制配置新建</button>
            <DeleteTrainingButton :task="task" @deleted="refresh" />
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
                  <button v-if="canRetrain(task)" class="button" type="button" @click="emit('retrain', task.config)">复制配置新建</button>
                  <DeleteTrainingButton :task="task" @deleted="refresh" />
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
.summary-card { display: flex; flex-direction: column; min-height: 270px; border-color: #cbd2dc; border-radius: 3px; box-shadow: 0 1px 3px #36415208; }
.summary-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 7px; min-height: 46px; margin: 0 12px; padding: 10px 0; border-bottom: 1px solid var(--line); }
.summary-header h2 { display: flex; align-items: center; gap: 7px; margin: 0; font-size: 12px; font-weight: 600; }
.summary-header svg { flex-shrink: 0; width: 16px; height: 16px; fill: none; stroke: #37506c; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.summary-badge { padding: 3px 5px; border: 1px solid #e1e7f1; border-radius: 2px; background: #eef3fc; color: #37506c; font-size: 10px; white-space: nowrap; }
.summary-badge[data-ready="true"] { color: #167553; background: #edf9f3; border-color: #c4e7d8; }
.summary-badge[data-ready="false"] { color: #83530e; background: #fff6e8; border-color: #eadbc2; }
.summary-content { display: grid; align-content: start; gap: 12px; padding: 12px; min-width: 0; }
.summary-card strong, .summary-card b { color: #152035; font-variant-numeric: tabular-nums; }
.summary-description { margin: 0; color: var(--muted); font-size: 11px; line-height: 1.6; }
.summary-footer { display: flex; align-items: center; min-height: 34px; margin-top: auto; padding: 8px 12px; border-top: 1px solid var(--line); background: #f7f8fc; color: var(--muted); font-size: 10px; line-height: 1.5; }
.environment-versions { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: Consolas, monospace; }
.device-row { display: flex; align-items: center; gap: 7px; min-width: 0; }
.device-row strong { min-width: 0; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.device-row small { flex-shrink: 0; margin-left: auto; color: var(--muted); font: 10px Consolas, monospace; }
.gpu-symbol { display: grid; place-items: center; flex-shrink: 0; width: 21px; height: 21px; color: #557e16; background: #eef5e3; border: 1px solid #d3e3bb; border-radius: 3px; font: 700 8px Arial, sans-serif; }
.summary-details { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 0; }
.summary-details > div { min-width: 0; padding: 8px; border: 1px solid #e3e8f1; background: #f6f8fd; }
.summary-details dt { color: var(--muted); font-size: 10px; }
.summary-details dd { margin: 6px 0 0; overflow-wrap: anywhere; color: #263b53; font: 600 12px/1.5 Consolas, 'Microsoft YaHei UI', monospace; }
.activity-counts { display: flex; align-items: center; justify-content: space-between; gap: 9px; }
.activity-counts > div { display: flex; align-items: baseline; gap: 5px; }
.activity-counts strong { font: 700 31px/1.2 Consolas, monospace; color: #37506c; }
.activity-counts b { font: 600 16px Consolas, monospace; }
.activity-counts span { color: var(--muted); font-size: 10px; }
.activity-counts i { color: #cbd2dc; font-size: 13px; font-style: normal; }
.active-task-preview { min-width: 0; padding: 10px; border: 1px solid #e1e8ef; background: #f4f9fc; color: var(--muted); font-size: 11px; }
.active-task-preview > div { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.active-task-preview strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.active-task-preview span { flex-shrink: 0; }
.active-task-preview progress { color: #4f6885; height: 5px; margin-top: 8px; }
.scheduler-slot { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 10px; }
.scheduler-slot strong { margin-left: auto; font-size: 11px; font-weight: 500; }
.slot-indicator { width: 15px; height: 7px; border: 1px solid #cbd2dc; background: #e6eaf0; }
.slot-indicator[data-busy="true"] { background: #37506c; border-color: #37506c; }
.comparison-title { font-size: 17px; }
.comparison-checks { display: grid; gap: 6px; }
.comparison-checks span { display: flex; align-items: center; gap: 7px; padding: 6px 8px; border: 1px solid #e1e7f1; background: #f6f8fd; color: #526176; font-size: 10px; }
.comparison-checks span::before { content: ''; width: 4px; height: 4px; background: #8c9bb0; }
.elapsed-value { display: flex; align-items: baseline; gap: 7px; }
.elapsed-value strong { font: 700 34px/1.1 Consolas, monospace; }
.elapsed-value span { color: var(--muted); font-size: 12px; }
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
@media (max-width: 600px) { .training-overview { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 960px) { .task-grid { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 440px) {
  .view-toggle { margin-left: 0; }
  .task-icon { display: none; }
  .card-header, .dataset-line, .task-progress { flex-wrap: wrap; }
}
</style>
