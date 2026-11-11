<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import TrainingCharts from '../components/training/TrainingCharts.vue'
import TrainingConfigPanel from '../components/training/TrainingConfigPanel.vue'
import DeleteTrainingButton from '../components/training/DeleteTrainingButton.vue'
import TrainingLogPanel from '../components/training/TrainingLogPanel.vue'
import TrainingPreview from '../components/training/TrainingPreview.vue'
import TrainingSystemPanel from '../components/training/TrainingSystemPanel.vue'
import ResumeTrainingDialog from '../components/training/ResumeTrainingDialog.vue'
import { useTrainingMonitor } from '../composables/useTrainingMonitor'
import { registerTrainingModel, trainingLogDownloadUrl } from '../api/training'
import { taskLabels } from '../domain'
import { terminalTrainingStates, trainingPhaseLabels, trainingStatusLabels } from '../types/training'
import type { TrainingConfig } from '../types/training'

const props = defineProps<{ taskId: string; initialTab?: 'logs' }>()
const emit = defineEmits<{ back: []; retrain: [config: TrainingConfig]; 'open-task': [id: string] }>()
const { task, metrics, logs, refreshing, refreshError, action, actionError, refresh, runAction } = useTrainingMonitor(() => props.taskId)
const logPanel = ref<InstanceType<typeof TrainingLogPanel>>()
const confirmDialog = ref<HTMLDialogElement>()
const actionLabel = computed(() => task.value?.status === 'running' ? '终止训练' : '取消任务')
const percent = computed(() => task.value?.status === 'succeeded' ? 100
  : task.value ? Math.min(100, Math.max(0, task.value.epoch / task.value.config.epochs * 100)) : 0)
const finished = computed(() => task.value && terminalTrainingStates.has(task.value.status))
const registering = ref(false)
const registrationError = ref('')
const resumeOpen = ref(false)
const tabs = [
  { id: 'overview', label: '概览' }, { id: 'logs', label: '日志流' },
  { id: 'metrics', label: '指标曲线' }, { id: 'system', label: '系统监控' },
  { id: 'config', label: '超参配置' }, { id: 'files', label: '文件管理' },
] as const
const activeTab = ref<(typeof tabs)[number]['id']>(props.initialTab ?? 'overview')
const metricNumber = new Intl.NumberFormat('zh-CN', { maximumSignificantDigits: 4 })
const startTime = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'medium' })
const evaluationKeys = computed<[string, string][]>(() => {
  if (task.value?.config.task === 'classify') return [['top1', 'Top-1'], ['top5', 'Top-5']]
  const keys: [string, string][] = [['map50', 'mAP@50'], ['map50_95', 'mAP@50–95'], ['precision', 'Precision'], ['recall', 'Recall']]
  if (task.value?.config.task === 'segment') keys.push(['maskMap50', 'Mask mAP@50'], ['maskMap50_95', 'Mask mAP@50–95'])
  return keys
})
const lossKeys = computed<[string, string][]>(() => {
  if (task.value?.config.task === 'classify') return [['clsLoss', '分类损失'], ['valLoss', '验证损失']]
  const keys: [string, string][] = [['boxLoss', '定位损失'], ['clsLoss', '分类损失'], ['dflLoss', 'DFL 损失']]
  if (task.value?.config.task === 'segment') keys.splice(3, 0, ['segLoss', '掩膜损失'])
  return keys
})

function metric(key: string) {
  const value = task.value?.metrics[key]
  return value !== undefined && Number.isFinite(value) ? metricNumber.format(value) : '—'
}

function duration(seconds?: number) {
  if (seconds === undefined || !Number.isFinite(seconds)) return '—'
  const minutes = Math.floor(seconds / 60)
  if (minutes >= 60) return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`
  return minutes ? `${minutes} 分钟` : `${Math.floor(seconds)} 秒`
}

function fileSize(bytes?: number) {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  return bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(1)} KiB` : `${(bytes / 1024 ** 2).toFixed(1)} MiB`
}

function requestAction() {
  confirmDialog.value?.showModal()
}

function confirmAction() {
  void runAction('cancel')
  confirmDialog.value?.close()
}

async function registerModel() {
  const id = props.taskId
  registering.value = true
  registrationError.value = ''
  try {
    const modelVersion = await registerTrainingModel(id)
    if (props.taskId === id && task.value?.id === id) task.value = { ...task.value, modelVersion }
  } catch (error) {
    if (props.taskId === id) registrationError.value = error instanceof Error ? error.message : '注册模型版本失败'
  } finally {
    if (props.taskId === id) registering.value = false
  }
}

watch(() => props.taskId, () => {
  confirmDialog.value?.close()
  registrationError.value = ''
  registering.value = false
  resumeOpen.value = false
})
watch([() => props.taskId, () => props.initialTab], ([, tab]) => {
  activeTab.value = tab ?? 'overview'
})
watch([logPanel, () => props.initialTab], ([panel, tab]) => {
  if (tab === 'logs' && activeTab.value === 'logs') panel?.focus()
}, { flush: 'post' })
</script>

<template>
  <section class="training-detail" aria-label="训练任务详情">
    <div class="detail-navigation">
      <button type="button" class="button" @click="emit('back')">← 返回训练任务</button>
      <span>模型训练 / <strong>实时监控</strong></span>
      <button type="button" class="button refresh" :disabled="refreshing || !!action" @click="refresh">
        {{ refreshing ? '正在刷新…' : '刷新数据' }}
      </button>
    </div>
    <div v-if="refreshError" class="notice error" role="alert">{{ refreshError }}</div>
    <div v-if="!task" class="notice" role="status">{{ refreshError ? '任务详情暂不可用' : '正在加载训练详情…' }}</div>
    <template v-else>
      <header class="task-header">
        <div class="header-line">
          <div class="task-heading">
            <h1>{{ task.config.name }}</h1>
            <span class="task-status" :data-status="task.status">{{ trainingStatusLabels[task.status] }}</span>
            <span v-if="!finished && task.phase" class="monitor-mode">
              {{ task.cancelRequested ? '正在终止' : trainingPhaseLabels[task.phase] ?? task.phase }}
            </span>
          </div>
          <div class="actions">
            <span v-if="!finished" class="monitor-mode">每 5 秒刷新</span>
            <button v-if="task.actions.includes('cancel')" type="button" class="button danger"
              :disabled="!!action || task.cancelRequested" @click="requestAction">
              {{ action || task.cancelRequested ? '处理中…' : actionLabel }}
            </button>
            <button v-if="task.resume?.available" type="button" class="button primary" @click="resumeOpen = true">恢复中断训练</button>
            <button v-if="task.modelVersion" type="button" class="button primary"
              @click="emit('retrain', { ...task.config, modelId: 'version:' + task.modelVersion.id, freeze: 0 })">使用此模型微调</button>
            <button v-if="finished" type="button" class="button" @click="emit('retrain', task.config)">复制配置新建</button>
            <DeleteTrainingButton :task="task" @deleted="emit('back')" />
          </div>
        </div>
        <p v-if="['failed', 'canceled'].includes(task.status) && task.resume?.reason" class="monitor-mode">恢复检查：{{ task.resume.reason }}</p>
        <div v-if="actionError || task.failure || task.error" class="notice error" role="alert">
          <strong>{{ actionError || task.failure?.summary || task.error }}</strong>
          <p v-if="task.failure">
            {{ task.failure.code }} · {{ trainingPhaseLabels[task.failure.stage] ?? task.failure.stage }}
            <template v-if="task.failure.exitCode != null"> · 退出码 {{ task.failure.exitCode }}</template>
          </p>
          <p v-if="task.failure?.suggestion">{{ task.failure.suggestion }}</p>
        </div>
      </header>

      <div class="telemetry" aria-label="训练任务摘要">
        <article class="task-info">
          <h2>任务信息</h2>
          <p class="task-id" :title="task.id">ID {{ task.id }}</p>
          <dl class="stat-grid">
            <div><dt>任务类型</dt><dd>{{ taskLabels[task.config.task] }}</dd></div>
            <div><dt>训练数据集</dt><dd>{{ task.datasetName }}</dd></div>
            <div><dt>基础模型</dt><dd>{{ task.modelName }}</dd></div>
            <div v-if="task.resumeFromTaskId"><dt>恢复自任务</dt><dd><button type="button" class="button" @click="emit('open-task', task.resumeFromTaskId)">查看原任务</button></dd></div>
            <div><dt>开始时间</dt><dd>{{ task.startedAt ? startTime.format(new Date(task.startedAt)) : '—' }}</dd></div>
          </dl>
        </article>
        <article>
          <h2>Epoch 进度</h2>
          <div class="progress-caption"><strong>{{ task.epoch }} / {{ task.config.epochs }}</strong><span>{{ percent.toFixed(1) }}%</span></div>
          <progress :value="percent" max="100" aria-label="训练进度"/>
          <div class="run-times"><span>耗时 {{ duration(task.elapsedSeconds) }}</span><span v-if="!finished">预计剩余 {{ duration(task.etaSeconds) }}</span></div>
        </article>
        <article>
          <h2>损失</h2>
          <dl class="stat-grid">
            <div v-for="[key, label] in lossKeys" :key="key"><dt>{{ label }}</dt><dd class="number">{{ metric(key) }}</dd></div>
          </dl>
        </article>
        <article>
          <h2>最新评估指标</h2>
          <dl class="stat-grid">
            <div v-for="[key, label] in evaluationKeys" :key="key"><dt>{{ label }}</dt><dd class="number">{{ metric(key) }}</dd></div>
          </dl>
        </article>
        <article>
          <h2>设备与学习率</h2>
          <dl class="stat-grid">
            <div><dt>设备</dt><dd>{{ task.device?.name ?? task.config.deviceId }}</dd></div>
            <div><dt>当前学习率</dt><dd class="number">{{ metric('learningRate') }}</dd></div>
            <div v-if="task.runtime?.processId"><dt>{{ finished ? '训练 PID' : 'PID' }}</dt><dd class="number">{{ task.runtime.processId }}</dd></div>
          </dl>
        </article>
      </div>

      <nav class="monitor-tabs" aria-label="实时监控面板">
        <button v-for="tab in tabs" :key="tab.id" type="button" :aria-pressed="activeTab === tab.id"
          @click="activeTab = tab.id">{{ tab.label }}</button>
      </nav>

      <div :key="task.id" class="monitor-panels">
        <div v-show="activeTab === 'overview' || activeTab === 'metrics'"
          class="monitor-grid" :class="{ 'with-preview': activeTab === 'overview' }">
          <TrainingCharts :task="task.config.task" :points="metrics"/>
          <TrainingPreview v-show="activeTab === 'overview'" :previews="task.previews"/>
        </div>
        <TrainingLogPanel v-show="activeTab === 'logs'" ref="logPanel" :entries="logs" :download-name="task.config.name"
          :active="activeTab === 'logs'" :download-url="trainingLogDownloadUrl(task.id)"/>
        <TrainingSystemPanel v-show="activeTab === 'system'" :task="task" :active="activeTab === 'system'"/>
        <TrainingConfigPanel v-show="activeTab === 'config'" :task="task" @retrain="emit('retrain', $event)"/>
        <div v-show="activeTab === 'files'" class="files-panel">
          <section class="artifacts">
            <h2>训练产物</h2>
            <p v-if="!task.artifacts.length" class="empty">任务尚未归档训练产物。</p>
            <div v-else class="artifact-table">
              <table>
                <thead><tr><th>文件</th><th>大小</th><th>SHA-256</th><th>操作</th></tr></thead>
                <tbody><tr v-for="artifact in task.artifacts" :key="artifact.id">
                  <th scope="row">{{ artifact.name }}</th><td>{{ fileSize(artifact.sizeBytes) }}</td>
                  <td class="artifact-digest" :title="artifact.sha256">{{ artifact.sha256 ?? '—' }}</td>
                  <td><a class="button" :href="artifact.url" :download="artifact.name" :aria-label="`下载 ${artifact.name}`">下载</a></td>
                </tr></tbody>
              </table>
            </div>
          </section>
          <section v-if="task.status === 'succeeded'" class="artifacts">
            <h2>模型版本</h2>
            <template v-if="task.modelVersion">
              <p>版本 {{ task.modelVersion.version }} · {{ task.modelVersion.validationStatus === 'verified' ? '已验证' : '待独立验证' }}</p>
              <p class="artifact-digest">权重 SHA-256 {{ task.modelVersion.sha256 }}</p>
            </template>
            <button v-else type="button" class="button primary" :disabled="registering" @click="registerModel">
              {{ registering ? '正在注册…' : '注册模型版本' }}
            </button>
            <p v-if="registrationError" class="notice error" role="alert">{{ registrationError }}</p>
          </section>
        </div>
      </div>
      <ResumeTrainingDialog v-if="resumeOpen" :task="task" @close="resumeOpen = false"
        @created="resumeOpen = false; emit('open-task', $event)" />
    </template>

    <dialog ref="confirmDialog" class="confirm-dialog" aria-labelledby="confirm-training-action">
      <form method="dialog">
        <h2 id="confirm-training-action">{{ actionLabel }}？</h2>
        <p>{{ task?.status === 'running' ? '确认后将请求停止该训练进程。' : '任务将从训练队列移除。' }}</p>
        <div class="actions">
          <button type="submit" class="button" autofocus>返回</button>
          <button type="button" class="button danger" @click="confirmAction">确认{{ actionLabel }}</button>
        </div>
      </form>
    </dialog>
  </section>
</template>

<style scoped>
.training-detail { display: grid; gap: 10px; min-width: 0; }
.detail-navigation, .header-line, .actions, .task-heading, .progress-caption, .run-times {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px;
}
.detail-navigation { font-size: 13px; color: var(--muted); }
.refresh { margin-left: auto; }
.task-header, .telemetry article, .notice, .artifacts {
  background: var(--surface); border: 1px solid var(--line); border-radius: 5px; padding: 12px 14px;
}
.header-line { justify-content: space-between; }
.task-heading { min-width: 0; }
h1 { margin: 0; font-size: clamp(18px, 2vw, 23px); overflow-wrap: anywhere; }
h2 { margin: 0 0 8px; font-size: 14px; }
.task-status, .monitor-mode { padding: 3px 8px; border-radius: 4px; background: var(--selected); font-size: 12px; white-space: nowrap; }
.monitor-mode { color: var(--muted); background: var(--soft); }
.task-status[data-status="running"], .task-status[data-status="succeeded"] { color: #156756; background: #e6f5f0; }
.task-status[data-status="failed"] { color: var(--danger); background: #fff0f1; }
.task-status[data-status="created"], .task-status[data-status="queued"] { color: #83530e; background: #fff3df; }
.artifact-digest { overflow-wrap: anywhere; }
dl { margin: 0; }
.stat-grid { display: grid; gap: 6px 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
dt { font-size: 12px; color: var(--muted); }
dd { margin: 2px 0 0; font-weight: 600; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.task-info dd { font-weight: 400; }
.progress-caption { font: 12px/1.4 Consolas, monospace; }
.progress-caption strong { font-size: 21px; }
.run-times { color: var(--muted); font-size: 11px; }
progress { display: block; width: 100%; height: 8px; margin: 6px 0 8px; accent-color: var(--primary); }
.telemetry { display: grid; grid-template-columns: minmax(0, 1.45fr) repeat(4, minmax(0, 1fr)); gap: 8px; }
.telemetry article { min-width: 0; }
.telemetry > article:not(.task-info) .stat-grid { align-items: center; }
.task-id { margin: 0 0 6px; overflow-wrap: anywhere; color: var(--muted); font: 11px/1.4 Consolas, monospace; }
.number { font: 600 14px/1.25 Consolas, monospace; }
.monitor-tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px 5px 0; border: 1px solid var(--line); background: var(--surface); border-radius: 5px; }
.monitor-tabs button { padding: 7px 13px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--muted); font-size: 13px; }
.monitor-tabs button:hover { background: var(--soft); }
.monitor-tabs button[aria-pressed="true"] { border-bottom-color: var(--primary); background: var(--selected); color: #294562; font-weight: 650; }
.monitor-panels, .monitor-grid { min-width: 0; }
.monitor-grid { display: grid; gap: 10px; }
.monitor-grid.with-preview { grid-template-columns: minmax(0, 1fr) minmax(260px, .62fr); }
.notice { color: var(--muted); font-size: 13px; }
.notice.error { color: var(--danger); background: #fff6f6; border-color: #e8b9bd; }
.task-header .notice { margin-top: 12px; }
.files-panel { display: grid; gap: 10px; }
.artifact-table { overflow: auto; }
.artifacts table { width: 100%; border-collapse: collapse; font-size: 12px; text-align: left; }
.artifacts th, .artifacts td { padding: 8px 10px; border-bottom: 1px solid var(--line); }
.artifacts thead { background: var(--soft); }
.artifacts table .artifact-digest { min-width: 130px; font: 11px Consolas, monospace; }
.artifacts th:last-child, .artifacts td:last-child { white-space: nowrap; }
.artifacts .empty { color: var(--muted); margin: 0; }
.artifacts a { text-decoration: none; }
.confirm-dialog { width: min(100% - 24px, 420px); padding: 18px; border: 1px solid var(--line); border-radius: 10px; color: var(--text); }
.confirm-dialog::backdrop { background: #1f2b415c; }
.confirm-dialog p { color: var(--muted); }
.confirm-dialog .actions { justify-content: flex-end; }
@media (max-width: 1240px) {
  .telemetry { grid-template-columns: repeat(auto-fit, minmax(min(100%, 170px), 1fr)); }
}
@media (max-width: 960px) { .monitor-grid.with-preview { grid-template-columns: minmax(0, 1fr); } }
</style>
