<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import TrainingCharts from '../components/training/TrainingCharts.vue'
import DeleteTrainingButton from '../components/training/DeleteTrainingButton.vue'
import TrainingLogPanel from '../components/training/TrainingLogPanel.vue'
import TrainingPreview from '../components/training/TrainingPreview.vue'
import { useTrainingMonitor } from '../composables/useTrainingMonitor'
import { registerTrainingModel } from '../api/training'
import { taskLabels } from '../domain'
import { terminalTrainingStates, trainingPhaseLabels, trainingStatusLabels } from '../types/training'
import type { TrainingConfig } from '../types/training'

const props = defineProps<{ taskId: string; initialTab?: 'logs' }>()
const emit = defineEmits<{ back: []; retrain: [config: TrainingConfig] }>()
const { task, metrics, logs, refreshing, refreshError, action, actionError, refresh, runAction } = useTrainingMonitor(() => props.taskId)
const logPanel = ref<InstanceType<typeof TrainingLogPanel>>()
const confirmDialog = ref<HTMLDialogElement>()
const actionLabel = computed(() => task.value?.status === 'running' ? '终止训练' : '取消任务')
const percent = computed(() => task.value?.status === 'succeeded' ? 100
  : task.value ? Math.min(100, Math.max(0, task.value.epoch / task.value.config.epochs * 100)) : 0)
const finished = computed(() => task.value && terminalTrainingStates.has(task.value.status))
const registering = ref(false)
const registrationError = ref('')
const metricNumber = new Intl.NumberFormat('zh-CN', { maximumSignificantDigits: 4 })
const device = computed(() => task.value?.device)
const evaluationKeys = computed<[string, string][]>(() => {
  if (task.value?.config.task === 'classify') return [['top1', 'Top-1'], ['top5', 'Top-5']]
  const keys: [string, string][] = [['map50', 'mAP@50'], ['map50_95', 'mAP@50–95'], ['precision', 'Precision'], ['recall', 'Recall']]
  if (task.value?.config.task === 'segment') keys.push(['maskMap50', 'Mask mAP@50'], ['maskMap50_95', 'Mask mAP@50–95'])
  return keys
})
const lossKeys = computed<[string, string][]>(() => {
  if (task.value?.config.task === 'classify') return [['clsLoss', '分类损失'], ['valLoss', '验证损失'], ['learningRate', '学习率']]
  const keys: [string, string][] = [['boxLoss', '定位损失'], ['clsLoss', '分类损失'], ['dflLoss', 'DFL 损失'], ['learningRate', '学习率']]
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
})
watch([logPanel, () => props.initialTab], ([panel, tab]) => {
  if (tab === 'logs') panel?.focus()
}, { flush: 'post' })
</script>

<template>
  <section class="training-detail" aria-label="训练任务详情">
    <div class="detail-navigation">
      <button type="button" class="button" @click="emit('back')">← 返回训练任务</button>
      <span>实时监控</span>
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
            <button v-if="finished" type="button" class="button primary" @click="emit('retrain', task.config)">再次训练</button>
            <DeleteTrainingButton :task="task" @deleted="emit('back')" />
          </div>
        </div>
        <div v-if="actionError || task.failure || task.error" class="notice error" role="alert">
          <strong>{{ actionError || task.failure?.summary || task.error }}</strong>
          <p v-if="task.failure">
            {{ task.failure.code }} · {{ trainingPhaseLabels[task.failure.stage] ?? task.failure.stage }}
            <template v-if="task.failure.exitCode != null"> · 退出码 {{ task.failure.exitCode }}</template>
          </p>
          <p v-if="task.failure?.suggestion">{{ task.failure.suggestion }}</p>
        </div>
        <div class="run-summary">
          <dl class="run-meta">
            <div><dt>任务类型</dt><dd>{{ taskLabels[task.config.task] }}</dd></div>
            <div><dt>基础模型</dt><dd>{{ task.modelName }}</dd></div>
            <div><dt>训练数据集</dt><dd>{{ task.datasetName }}</dd></div>
            <div><dt>输入尺寸 / Batch</dt><dd>{{ task.config.imageSize }} / {{ task.config.batchSize }}</dd></div>
          </dl>
          <div class="progress-block">
            <div class="progress-caption"><strong>Epoch {{ task.epoch }} / {{ task.config.epochs }}</strong><span>{{ percent.toFixed(1) }}%</span></div>
            <progress :value="percent" max="100" aria-label="训练进度"/>
            <div class="run-times"><span>已训练 {{ duration(task.elapsedSeconds) }}</span><span v-if="!finished">预计剩余 {{ duration(task.etaSeconds) }}</span></div>
          </div>
        </div>
      </header>

      <div class="telemetry">
        <article>
          <h2>计算设备</h2>
          <p class="device-name">{{ device?.name ?? '本机 CPU' }}</p>
          <dl class="stat-grid">
            <div><dt>执行方式</dt><dd>单任务运行</dd></div>
            <div v-if="task.snapshotDigest"><dt>数据快照</dt><dd :title="task.snapshotDigest">{{ task.snapshotDigest.slice(0, 12) }}</dd></div>
          </dl>
        </article>
        <article>
          <h2>生效配置</h2>
          <dl class="stat-grid">
            <div><dt>优化器</dt><dd>{{ task.config.optimizer }}</dd></div>
            <div><dt>随机种子</dt><dd>{{ task.config.seed }}</dd></div>
            <div><dt>AMP</dt><dd>{{ task.config.amp ? '启用' : '关闭' }}</dd></div>
            <div><dt>早停耐心值</dt><dd>{{ task.config.patience || '关闭' }}</dd></div>
          </dl>
        </article>
        <article>
          <h2>最新评估指标</h2>
          <dl class="stat-grid">
            <div v-for="[key, label] in evaluationKeys" :key="key"><dt>{{ label }}</dt><dd>{{ metric(key) }}</dd></div>
          </dl>
        </article>
        <article>
          <h2>损失与学习率</h2>
          <dl class="stat-grid">
            <div v-for="[key, label] in lossKeys" :key="key"><dt>{{ label }}</dt><dd>{{ metric(key) }}</dd></div>
          </dl>
        </article>
      </div>

      <div class="monitor-grid">
        <TrainingCharts :key="task.id" :task="task.config.task" :points="metrics"/>
        <TrainingPreview :key="task.id" :previews="task.previews"/>
      </div>
      <TrainingLogPanel :key="task.id" ref="logPanel" :entries="logs" :download-name="task.config.name"/>
      <section v-if="task.artifacts.length" class="artifacts">
        <h2>训练产物</h2>
        <a v-for="artifact in task.artifacts" :key="artifact.id" class="button" :href="artifact.url" :download="artifact.name">
          下载 {{ artifact.name }}
        </a>
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
.training-detail { display: grid; gap: 14px; min-width: 0; }
.detail-navigation, .header-line, .actions, .task-heading, .progress-caption, .run-times {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px;
}
.detail-navigation { font-size: 13px; color: var(--muted); }
.refresh { margin-left: auto; }
.task-header, .telemetry article, .notice, .artifacts {
  background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px;
}
.header-line { justify-content: space-between; }
.task-heading { min-width: 0; }
h1 { margin: 0; font-size: clamp(18px, 2vw, 23px); overflow-wrap: anywhere; }
h2 { margin: 0 0 8px; font-size: 14px; }
.task-status, .monitor-mode { padding: 3px 8px; border-radius: 4px; background: var(--selected); font-size: 12px; white-space: nowrap; }
.monitor-mode { color: var(--muted); background: var(--soft); }
.task-status[data-status="running"], .task-status[data-status="succeeded"] { color: #156756; background: #e6f5f0; }
.task-status[data-status="failed"] { color: var(--danger); background: #fff0f1; }
.task-status[data-status="created"] { color: #83530e; background: #fff3df; }
.artifact-digest { overflow-wrap: anywhere; }
.run-summary { display: grid; grid-template-columns: minmax(0, 1fr) minmax(min(100%, 180px), 270px); gap: 12px 20px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line); }
dl { margin: 0; }
.run-meta, .stat-grid { display: grid; gap: 8px 14px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 102px), 1fr)); }
dt { font-size: 12px; color: var(--muted); }
dd { margin: 2px 0 0; font-weight: 600; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.progress-caption, .run-times { justify-content: space-between; }
.progress-caption { font: 12px/1.4 Consolas, monospace; }
.run-times { color: var(--muted); font-size: 11px; }
progress { display: block; width: 100%; height: 8px; margin: 5px 0; accent-color: var(--primary); }
.telemetry { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 212px), 1fr)); gap: 10px; }
.telemetry article { min-width: 0; }
.device-name { margin: 0 0 7px; font-weight: 600; }
.monitor-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(min(100%, 235px), .56fr); gap: 12px; }
.notice { color: var(--muted); font-size: 13px; }
.notice.error { color: var(--danger); background: #fff6f6; border-color: #e8b9bd; }
.task-header .notice { margin-top: 12px; }
.artifacts { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.artifacts h2 { margin: 0 8px 0 0; }
.artifacts a { text-decoration: none; }
.confirm-dialog { width: min(100% - 24px, 420px); padding: 18px; border: 1px solid var(--line); border-radius: 10px; color: var(--text); }
.confirm-dialog::backdrop { background: #1f2b415c; }
.confirm-dialog p { color: var(--muted); }
.confirm-dialog .actions { justify-content: flex-end; }
@media (max-width: 960px) { .monitor-grid { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 690px) { .run-summary { grid-template-columns: minmax(0, 1fr); } }
</style>
