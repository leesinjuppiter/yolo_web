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
import { registerTrainingModel, trainingArtifactsDownloadUrl, trainingLogDownloadUrl } from '../api/training'
import { taskLabels } from '../domain'
import { terminalTrainingStates, trainingPhaseLabels, trainingStatusLabels } from '../types/training'
import type { TrainingConfig } from '../types/training'

const props = defineProps<{ taskId: string; initialTab?: 'logs' }>()
const emit = defineEmits<{ back: []; retrain: [config: TrainingConfig]; 'open-task': [id: string] }>()
const { task, metrics, logs, refreshing, refreshError, action, actionError, refresh, runAction } = useTrainingMonitor(() => props.taskId)
const logPanel = ref<InstanceType<typeof TrainingLogPanel>>()
const confirmDialog = ref<HTMLDialogElement>()
const registrationDialog = ref<HTMLDialogElement>()
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
const startClock = new Intl.DateTimeFormat('zh-CN', { timeStyle: 'medium' })
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
const primaryLossKeys = computed<[string, string][]>(() => task.value?.config.task === 'classify'
  ? [['clsLoss', '分类损失 · train'], ['valLoss', '验证损失 · val']]
  : [['boxLoss', '定位损失 · train'], ['valBoxLoss', '定位损失 · val']])
const secondaryLossKeys = computed(() => task.value?.config.task === 'classify' ? [] : lossKeys.value.slice(1))

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

function requestRegistration() {
  if (registering.value || task.value?.status !== 'succeeded' || task.value.modelVersion) return
  registrationError.value = ''
  registrationDialog.value?.showModal()
}

function closeRegistration() {
  if (!registering.value) registrationDialog.value?.close()
}

async function registerModel() {
  if (registering.value || task.value?.id !== props.taskId || task.value.status !== 'succeeded' || task.value.modelVersion) return
  const id = props.taskId
  registering.value = true
  registrationError.value = ''
  try {
    const modelVersion = await registerTrainingModel(id)
    if (props.taskId === id && task.value?.id === id) {
      task.value = { ...task.value, modelVersion }
      registrationDialog.value?.close()
    }
  } catch (error) {
    if (props.taskId === id) registrationError.value = error instanceof Error ? error.message : '注册模型版本失败'
  } finally {
    if (props.taskId === id) registering.value = false
  }
}

watch(() => props.taskId, () => {
  confirmDialog.value?.close()
  registrationDialog.value?.close()
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
            <span v-if="!finished" class="monitor-mode">变化时更新</span>
            <button v-if="task.actions.includes('cancel')" type="button" class="button danger"
              :disabled="!!action || task.cancelRequested" @click="requestAction">
              {{ action || task.cancelRequested ? '处理中…' : actionLabel }}
            </button>
            <button v-if="task.resume?.available" type="button" class="button primary" @click="resumeOpen = true">恢复中断训练</button>
            <button v-if="task.modelVersion" type="button" class="button primary"
              @click="emit('retrain', { ...task.config, modelId: 'version:' + task.modelVersion.id, freeze: 0 })">使用此模型微调</button>
            <button v-if="finished" type="button" class="button" @click="emit('retrain', task.config)">复制配置新建</button>
            <button v-if="task.status === 'succeeded' && !task.modelVersion" type="button" class="button primary"
              :disabled="registering" @click="requestRegistration">{{ registering ? '正在注册…' : '注册模型版本' }}</button>
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
          <div class="summary-heading">
            <h2><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="1"/><path d="M4 10h16M10 4v16M15 10v10M10 15h10"/></svg>任务信息</h2>
            <span class="summary-status" :data-status="task.status">{{ trainingStatusLabels[task.status] }}</span>
          </div>
          <div class="summary-body">
          <strong class="summary-task-name" :title="task.config.name">{{ task.config.name }}</strong>
          <p class="task-id" :title="task.id"><span>UUID</span><span>{{ task.id }}</span></p>
          <dl class="stat-grid">
            <div><dt>任务类型</dt><dd>{{ taskLabels[task.config.task] }}</dd></div>
            <div><dt>训练数据集</dt><dd :title="task.datasetName">{{ task.datasetName }}<span v-if="task.datasetImageCount != null">（{{ task.datasetImageCount.toLocaleString('zh-CN') }} 张）</span></dd></div>
            <div><dt>基础模型</dt><dd :title="task.modelName">{{ task.modelName }}</dd></div>
            <div v-if="task.resumeFromTaskId"><dt>恢复自任务</dt><dd><button type="button" class="button" @click="emit('open-task', task.resumeFromTaskId)">查看原任务</button></dd></div>
          </dl>
          </div>
          <footer class="summary-footer"><span :title="task.startedAt ? startTime.format(new Date(task.startedAt)) : undefined">启动 {{ task.startedAt ? startClock.format(new Date(task.startedAt)) : '—' }}</span><strong>耗时 {{ duration(task.elapsedSeconds) }}</strong></footer>
        </article>
        <article class="epoch-card">
          <div class="summary-heading">
            <h2><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6a8 8 0 0 0-13 6M6 18a8 8 0 0 0 13-6M18 2v4h-4M6 22v-4h4"/><circle cx="12" cy="12" r="3"/></svg>Epoch 进度</h2>
          </div>
          <div class="summary-body">
          <div class="progress-caption"><div><strong>{{ task.epoch }}</strong><span> / {{ task.config.epochs }}</span></div><b>{{ percent.toFixed(1) }}<small>%</small></b></div>
          <progress :value="percent" max="100" aria-label="训练进度"/>
          <div class="progress-ticks" aria-hidden="true"><span v-for="tick in [0, 25, 50, 75, 100]" :key="tick">{{ tick }}%</span></div>
          <dl class="summary-tiles epoch-details">
            <div><dt>目标轮数</dt><dd>{{ task.config.epochs }} <small>epoch</small></dd></div>
            <div><dt>{{ finished ? '已完成轮数' : '预计剩余' }}</dt><dd>{{ finished ? task.epoch : duration(task.etaSeconds) }}</dd></div>
          </dl>
          </div>
          <footer class="summary-footer"><span>总耗时 {{ duration(task.elapsedSeconds) }}</span><strong>{{ trainingStatusLabels[task.status] }}</strong></footer>
        </article>
        <article class="loss-card">
          <div class="summary-heading">
            <h2><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16M8 3v6M16 9v6M10 15v6"/></svg>损失</h2>
            <span class="summary-tag">Epoch {{ task.epoch }}</span>
          </div>
          <div class="summary-body">
          <dl class="primary-losses">
            <div v-for="[key, label] in primaryLossKeys" :key="key"><dt>{{ label }}</dt><dd>{{ metric(key) }}</dd></div>
          </dl>
          <dl v-if="secondaryLossKeys.length" class="stat-grid loss-details">
            <div v-for="[key, label] in secondaryLossKeys" :key="key"><dt>{{ label }}</dt><dd class="number">{{ metric(key) }}</dd></div>
          </dl>
          </div>
          <footer class="summary-footer"><span>损失来源</span><strong>最新训练轮次</strong></footer>
        </article>
        <article class="evaluation-card">
          <div class="summary-heading">
            <h2><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4H5v17h14V4h-3M9 3h6v4H9zM8 11h8M8 15h8M8 18h5"/></svg>最新评估指标</h2>
          </div>
          <div class="summary-body">
          <dl class="summary-tiles metric-tiles">
            <div v-for="[key, label] in evaluationKeys.slice(0, 2)" :key="key"><dt>{{ label }}</dt><dd>{{ metric(key) }}</dd></div>
          </dl>
          <dl v-if="evaluationKeys.length > 2" class="stat-grid evaluation-details">
            <div v-for="[key, label] in evaluationKeys.slice(2)" :key="key"><dt>{{ label }}</dt><dd class="number">{{ metric(key) }}</dd></div>
          </dl>
          </div>
          <footer class="summary-footer"><span>训练验证集</span><strong>Epoch {{ task.epoch }}</strong></footer>
        </article>
        <article class="device-card">
          <div class="summary-heading">
            <h2><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 9h6v6H9zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg>设备信息</h2>
            <span class="summary-tag">{{ task.config.deviceId }}</span>
          </div>
          <div class="summary-body">
          <strong class="device-name">{{ task.device?.name ?? task.config.deviceId }}</strong>
          <dl class="summary-tiles device-versions">
            <div><dt>PyTorch</dt><dd>{{ task.runtime?.versions?.torch ?? '—' }}</dd></div>
            <div><dt>Python</dt><dd>{{ task.runtime?.versions?.python ?? '—' }}</dd></div>
          </dl>
          <dl class="stat-grid">
            <div><dt>{{ task.device?.kind === 'cuda' ? '设备总显存' : '设备内存' }}</dt><dd>{{ task.device?.memoryBytes ? (task.device.memoryBytes / 1024 ** 3).toFixed(1) + ' GiB' : '—' }}</dd></div>
            <div><dt>混合精度设置</dt><dd>{{ task.config.amp ? 'AMP 开启' : 'AMP 关闭' }}</dd></div>
          </dl>
          </div>
          <footer class="summary-footer"><span>Ultralytics</span><strong>{{ task.runtime?.versions?.ultralytics ?? '—' }}</strong></footer>
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
            <div class="artifact-heading">
              <h2>训练产物</h2>
              <a v-if="finished && task.artifacts.length" class="button" :href="trainingArtifactsDownloadUrl(task.id)"
                :download="`training-${task.id}-artifacts.zip`">下载训练产物 ZIP</a>
            </div>
            <p v-if="!task.artifacts.length" class="empty">任务尚未归档训练产物。</p>
            <div v-else class="artifact-table">
              <table>
                <thead><tr><th>文件</th><th>大小</th><th>SHA-256</th></tr></thead>
                <tbody><tr v-for="artifact in task.artifacts" :key="artifact.id">
                  <th scope="row">{{ artifact.name }}</th><td>{{ fileSize(artifact.sizeBytes) }}</td>
                  <td class="artifact-digest" :title="artifact.sha256">{{ artifact.sha256 ?? '—' }}</td>
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
            <p v-else>尚未注册，可使用顶部操作区的“注册模型版本”。</p>
          </section>
        </div>
      </div>
      <ResumeTrainingDialog v-if="resumeOpen" :task="task" @close="resumeOpen = false"
        @created="resumeOpen = false; emit('open-task', $event)" />
    </template>

    <dialog ref="registrationDialog" class="confirm-dialog" aria-labelledby="confirm-model-registration"
      @cancel.prevent="closeRegistration">
      <h2 id="confirm-model-registration">确认注册模型版本？</h2>
      <p>将使用训练任务「{{ task?.config.name }}」的最优权重注册模型版本，并记录来源训练任务和数据快照。</p>
      <p>注册后可在模型仓库查看，该版本仍需独立评估。</p>
      <p v-if="registrationError" class="notice error" role="alert">{{ registrationError }}</p>
      <div class="actions">
        <button type="button" class="button" :disabled="registering" autofocus @click="closeRegistration">取消</button>
        <button type="button" class="button primary" :disabled="registering" @click="registerModel">{{ registering ? '正在注册…' : '确认注册' }}</button>
      </div>
    </dialog>
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
.detail-navigation, .header-line, .actions, .task-heading, .progress-caption {
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
.telemetry { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.telemetry article { display: flex; flex-direction: column; min-width: 0; min-height: 256px; padding: 0; border-color: #cbd2dc; border-radius: 3px; box-shadow: 0 1px 3px #3641520a; }
.summary-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 7px; min-height: 48px; margin: 0 12px; padding: 11px 0; border-bottom: 1px solid var(--line); }
.summary-heading h2 { display: flex; align-items: center; gap: 7px; margin: 0; font-size: 13px; }
.summary-heading svg { width: 17px; height: 17px; flex-shrink: 0; fill: none; stroke: #37506c; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.summary-status, .summary-tag { padding: 2px 5px; border: 1px solid var(--line); border-radius: 2px; color: #37506c; background: #f0f4fc; font: 11px/1.4 Consolas, monospace; }
.summary-status { display: inline-flex; align-items: center; gap: 5px; font-family: inherit; white-space: nowrap; }
.summary-status::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.summary-status[data-status="succeeded"], .summary-status[data-status="running"] { color: #25752b; background: #eaf7ec; border-color: #badcbe; }
.summary-status[data-status="failed"] { color: var(--danger); background: #fff0f1; border-color: #e8b9bd; }
.summary-status[data-status="queued"], .summary-status[data-status="created"] { color: #83530e; background: #fff3df; border-color: #ead3b1; }
.summary-body { display: grid; align-content: start; gap: 12px; padding: 12px; }
.summary-task-name { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.task-id { display: flex; align-items: center; gap: 5px; min-width: 0; margin: -7px 0 0; color: var(--muted); font: 10px/1.5 Consolas, monospace; }
.task-id span:first-child { padding: 0 4px; border: 1px solid var(--line); background: var(--soft); }
.task-id span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stat-grid { display: grid; gap: 8px; }
.stat-grid > div { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; min-width: 0; }
dt { color: var(--muted); font-size: 11px; }
.stat-grid dt { flex-shrink: 0; }
dd { min-width: 0; margin: 0; font-size: 12px; font-weight: 600; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.stat-grid dd { text-align: right; }
.task-info .stat-grid { padding-top: 10px; border-top: 1px solid var(--line); }
.task-info .stat-grid dd { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.summary-footer { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 5px 8px; margin-top: auto; padding: 9px 12px; border-top: 1px solid var(--line); background: #f7f8fc; color: var(--muted); font-size: 10px; }
.summary-footer strong { color: #37506c; font-weight: 500; font-variant-numeric: tabular-nums; }
.progress-caption { justify-content: space-between; flex-wrap: nowrap; gap: 8px; font: 12px/1.3 Consolas, monospace; }
.progress-caption strong { font-size: clamp(23px, 1.7vw, 30px); color: var(--text); }
.progress-caption span { color: var(--muted); }
.progress-caption b { color: #37506c; font-size: clamp(19px, 1.4vw, 24px); }
.progress-caption small { font-size: .75em; }
.epoch-card progress { display: block; width: 100%; height: 8px; margin: 3px 0 0; overflow: hidden; border: 0; border-radius: 4px; background: #e1e7f0; accent-color: #4f6885; }
.epoch-card progress::-webkit-progress-bar { background: #e1e7f0; border-radius: 4px; }
.epoch-card progress::-webkit-progress-value { background: #4f6885; border-radius: 4px; }
.epoch-card progress::-moz-progress-bar { background: #4f6885; border-radius: 4px; }
.progress-ticks { display: flex; justify-content: space-between; margin-top: -6px; color: var(--muted); font: 9px/1.4 Consolas, monospace; }
.summary-tiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.summary-tiles > div { min-width: 0; padding: 9px; background: #f6f8fd; }
.summary-tiles dd { margin-top: 6px; font-family: Consolas, monospace; }
.epoch-details { padding-top: 10px; border-top: 1px solid var(--line); }
.epoch-details dd { font-size: 13px; }
.epoch-details small { font-size: 10px; font-weight: 400; color: var(--muted); }
.primary-losses { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.primary-losses > div + div { border-left: 1px solid var(--line); padding-left: 10px; }
.primary-losses dd, .metric-tiles dd { margin-top: 7px; font: 700 clamp(22px, 1.7vw, 28px)/1.2 Consolas, monospace; }
.primary-losses > div + div dd { color: #37506c; }
.metric-tiles > div { border: 1px solid #e2e6ef; }
.metric-tiles > div + div dd { color: #25752b; }
.loss-details, .evaluation-details { padding-top: 12px; border-top: 1px solid var(--line); }
.number { font: 600 12px/1.4 Consolas, monospace; }
.device-name { font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
.device-versions > div { padding: 0; background: transparent; }
.device-versions dd { font-size: 11px; font-weight: 500; }
.device-card .stat-grid { padding-top: 10px; border-top: 1px solid var(--line); }
.monitor-tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px 5px 0; border: 1px solid var(--line); background: var(--surface); border-radius: 5px; }
.monitor-tabs button { padding: 7px 13px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--muted); font-size: 13px; }
.monitor-tabs button:hover { background: var(--soft); }
.monitor-tabs button[aria-pressed="true"] { border-bottom-color: var(--primary); background: var(--selected); color: #294562; font-weight: 650; }
.monitor-panels, .monitor-grid { min-width: 0; }
.monitor-grid { display: grid; gap: 10px; }
.monitor-grid.with-preview { grid-template-columns: minmax(0, 1fr); }
.notice { color: var(--muted); font-size: 13px; }
.notice.error { color: var(--danger); background: #fff6f6; border-color: #e8b9bd; }
.task-header .notice { margin-top: 12px; }
.files-panel { display: grid; gap: 10px; }
.artifact-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.artifact-heading h2 { margin: 0; }
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
@media (max-width: 1380px) {
  .telemetry { grid-template-columns: repeat(6, minmax(0, 1fr)); }
  .telemetry article { grid-column: span 2; }
  .telemetry .evaluation-card, .telemetry .device-card { grid-column: span 3; }
}
@media (max-width: 1000px) { .telemetry { grid-template-columns: repeat(2, minmax(0, 1fr)); } .telemetry article, .telemetry .evaluation-card, .telemetry .device-card { grid-column: auto; } }
@media (max-width: 640px) { .telemetry { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 960px) { .monitor-grid.with-preview { grid-template-columns: minmax(0, 1fr); } }
</style>
