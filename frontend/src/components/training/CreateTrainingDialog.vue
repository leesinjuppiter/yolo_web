<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { checkTraining, createTraining, DuplicateTrainingNameError, getTrainingOptions, listTrainingDatasets } from '../../api/training'
import { selectableDatasetTasks, taskLabels } from '../../domain'
import type { SelectableDatasetTask, Split } from '../../domain'
import type { TrainingConfig, TrainingDatasetSummary, TrainingOptions, TrainingPreflight } from '../../types/training'
import { createUuid } from '../../utils/id'

const props = defineProps<{
  datasetsRevision?: number
  datasetId?: string
  initialConfig?: TrainingConfig
}>()
const emit = defineEmits<{
  close: []
  created: [id: string]
}>()

const dialog = ref<HTMLDialogElement>()
const nameWarning = ref<HTMLDialogElement>()
const nameInput = ref<HTMLInputElement>()
const options = ref<TrainingOptions>()
const optionsLoading = ref(true)
const optionsError = ref('')
const deviceWarning = ref('')
const datasets = ref<TrainingDatasetSummary[]>([])
const datasetsLoading = ref(true)
const datasetsError = ref('')
const submitError = ref('')
const warnings = ref<string[]>([])
const busy = ref(false)
let submission: { payload: string; key: string } | undefined
let datasetRequest = 0
const optionsRequest = new AbortController()
const draft = reactive<TrainingConfig>(props.initialConfig ? { ...props.initialConfig } : {
  name: '',
  task: 'detect',
  datasetId: props.datasetId ?? '',
  modelId: '',
  deviceId: '',
  epochs: 20,
  batchSize: 4,
  imageSize: 320,
  optimizer: '',
  learningRate: 0.01,
  finalLearningRate: 0.01,
  seed: 42,
  patience: 10,
  amp: false,
  freeze: 0,
  workers: 0,
  augmentation: '',
})
draft.freeze ??= 0
draft.workers ??= 0
const earlyStopping = ref(draft.patience > 0)
const iterationMode = Boolean(props.initialConfig?.manifestId)
const manifestReport = ref<TrainingPreflight>()
const initialization = ref<'scratch' | 'pretrained'>(draft.modelId.endsWith('.pt') || draft.modelId.startsWith('version:') ? 'pretrained' : 'scratch')
watch(draft, () => { warnings.value = [] })
const splits: { key: Split | 'unassigned'; label: string }[] = [
  { key: 'train', label: '训练集' },
  { key: 'val', label: '验证集' },
  { key: 'test', label: '测试集' },
  { key: 'unassigned', label: '未分集' },
]

const compatibleDatasets = computed(() => datasets.value.filter(dataset => dataset.task === draft.task))
const dataset = computed(() => compatibleDatasets.value.find(item => item.id === draft.datasetId))
const models = computed(() => options.value?.models.filter(model => model.task === draft.task
  && Boolean(model.pretrained) === (initialization.value === 'pretrained')) ?? [])
const selectedModel = computed(() => models.value.find(model => model.id === draft.modelId))
const selectedDevice = computed(() => options.value?.devices.find(device => device.id === draft.deviceId))
const isCuda = computed(() => selectedDevice.value?.kind === 'cuda')
const datasetError = computed(() => iterationMode ? manifestReport.value?.errors.map(issue => issue.message).join('；') ?? '' : dataset.value?.errors.map(issue => issue.message).join('；') ?? '')
const splitSummary = computed(() => {
  const counts = { train: 0, val: 0, test: 0, ...(iterationMode ? manifestReport.value?.splitCounts : dataset.value?.splitCounts), unassigned: iterationMode ? 0 : dataset.value?.unassignedCount ?? 0 }
  const total = Object.values(counts).reduce((sum, count) => sum + count, 0)
  return {
    total,
    splits: splits.map(split => ({
      ...split,
      count: counts[split.key],
      percent: total ? counts[split.key] / total * 100 : 0,
    })),
  }
})
const canSubmit = computed(() => Boolean(
  options.value && !optionsLoading.value && !optionsError.value && draft.name.trim()
    && (iterationMode ? manifestReport.value : dataset.value) && !datasetError.value && selectedModel.value && draft.modelId && draft.deviceId && draft.optimizer && draft.augmentation
    && !busy.value && !datasetsLoading.value && !datasetsError.value
))

watch(() => props.datasetsRevision, () => { void loadDatasets() })
watch(isCuda, enabled => { if (!enabled) draft.amp = false })
watch(initialization, mode => { if (mode === 'scratch') draft.freeze = 0 })

watch(models, choices => {
  if (!iterationMode && !choices.some(model => model.id === draft.modelId)) draft.modelId = choices[0]?.id ?? ''
})

function selectTask(task: SelectableDatasetTask) {
  if (iterationMode) return
  if (task === draft.task) return
  draft.task = task
  draft.datasetId = ''
  submitError.value = ''
}

async function loadOptions() {
  optionsLoading.value = true
  optionsError.value = ''
  try {
    const result = await getTrainingOptions(optionsRequest.signal)
    const initialModel = result.models.find(model => model.id === draft.modelId)
    if (initialModel) initialization.value = initialModel.pretrained ? 'pretrained' : 'scratch'
    options.value = result
    if (!result.devices.some(device => device.id === draft.deviceId)) {
      deviceWarning.value = draft.deviceId ? '原配置的设备当前不可用，请重新选择设备。' : ''
      draft.deviceId = props.initialConfig?.deviceId ? '' : result.devices[0]?.id ?? ''
    }
    if (!result.optimizers.includes(draft.optimizer)) draft.optimizer = result.optimizers[0] ?? ''
    if (!result.augmentations.some(item => item.id === draft.augmentation)) {
      draft.augmentation = result.augmentations[0]?.id ?? ''
    }
    if (iterationMode) manifestReport.value = await checkTraining(draft)
  } catch (error) {
    if (!optionsRequest.signal.aborted) optionsError.value = error instanceof Error ? error.message : '读取训练选项失败'
  } finally {
    optionsLoading.value = false
  }
}

async function loadDatasets() {
  const requestId = ++datasetRequest
  datasetsLoading.value = true
  datasetsError.value = ''
  try {
    const result = await listTrainingDatasets(optionsRequest.signal)
    if (optionsRequest.signal.aborted || requestId !== datasetRequest) return
    datasets.value = result
    const preselected = result.find(item => item.id === draft.datasetId)
    if (preselected) draft.task = preselected.task
  } catch (error) {
    if (!optionsRequest.signal.aborted && requestId === datasetRequest) datasetsError.value = error instanceof Error ? error.message : '读取数据集摘要失败'
  } finally {
    if (requestId === datasetRequest) datasetsLoading.value = false
  }
}

onMounted(() => {
  dialog.value?.showModal()
  void loadOptions()
  void loadDatasets()
})
onBeforeUnmount(() => optionsRequest.abort())

function close() {
  if (!busy.value) emit('close')
}

function updateEarlyStopping() {
  if (earlyStopping.value && !draft.patience) draft.patience = 10
}

function focusNameInput() {
  nameInput.value?.focus()
  nameInput.value?.select()
}

async function submit() {
  if (!canSubmit.value || (!iterationMode && !dataset.value)) return
  submitError.value = ''
  if (draft.learningRate <= 0 || draft.finalLearningRate <= 0) {
    submitError.value = '初始学习率与最终学习率比例必须大于 0。'
    return
  }
  busy.value = true
  try {
    const config = {
      ...draft,
      name: draft.name.trim(),
      patience: earlyStopping.value ? draft.patience : 0,
      amp: isCuda.value && draft.amp,
      freeze: selectedModel.value?.pretrained ? draft.freeze ?? 0 : 0,
      workers: draft.workers ?? 0,
    }
    const payload = JSON.stringify(config)
    if (submission?.payload !== payload) {
      const result = await checkTraining(config)
      if (result.errors.length) {
        submitError.value = result.errors.map(issue => issue.message).join('；')
        return
      }
      const currentWarnings = result.warnings.map(issue => issue.message)
      if (currentWarnings.length && currentWarnings.join('\n') !== warnings.value.join('\n')) {
        warnings.value = currentWarnings
        return
      }
      submission = { payload, key: createUuid() }
    }
    const task = await createTraining(config, submission.key)
    emit('created', task.id)
  } catch (error) {
    if (error instanceof DuplicateTrainingNameError) nameWarning.value?.showModal()
    else submitError.value = error instanceof Error ? error.message : '创建训练任务失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <dialog ref="dialog" class="training-dialog" aria-labelledby="training-dialog-title" @cancel.prevent="close">
    <form class="training-form" @submit.prevent="submit">
      <header class="dialog-header">
        <span class="header-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M4 19V5m0 14h16M7 15l4-4 3 2 5-6m-4 0h4v4" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </span>
        <div>
          <div class="title-row">
            <h2 id="training-dialog-title">新建训练任务</h2>
            <span class="compute-badge">{{ selectedDevice?.name ?? '选择执行设备' }}</span>
          </div>
          <p>选择训练数据、初始化模型与执行设备，将任务提交到训练队列。</p>
        </div>
        <button type="button" class="button close-button" aria-label="关闭新建训练任务" :disabled="busy" @click="close">×</button>
      </header>

      <div class="dialog-content">
        <p v-if="iterationMode" class="message">主动学习固定输入：基线模型、任务类型和数据集已锁定。训练将使用已复核清单，不扫描数据集中的其他标注。清单：{{ draft.manifestDigest }}</p>
        <p v-if="optionsLoading" class="message" role="status">正在读取模型、设备及训练选项…</p>
        <div v-else-if="optionsError" class="message error-row" role="alert">
          {{ optionsError }}
          <button type="button" class="button" @click="loadOptions">重试</button>
        </div>
        <fieldset class="form-fields" :disabled="busy">
          <section class="form-section" aria-labelledby="training-basic">
            <h3 id="training-basic"><span>01</span> 基础任务信息</h3>
            <div class="field-grid basic-grid">
              <label class="field">
                <span>任务名称 <b>*</b></span>
                <input ref="nameInput" v-model.trim="draft.name" type="text" maxlength="120" required autofocus placeholder="例如 coal-gangue-obb-v1">
              </label>
              <div class="field">
                <span>任务类型 <b>*</b></span>
                <div class="task-options" role="group" aria-label="任务类型">
                  <button v-for="task in selectableDatasetTasks" :key="task" type="button" class="button choice"
                    :disabled="iterationMode" :aria-pressed="draft.task === task" @click="selectTask(task)">{{ taskLabels[task] }}</button>
                </div>
              </div>
              <div class="field full-width">
                <span>模型初始化</span>
                <div class="task-options" role="group" aria-label="模型初始化方式">
                  <button type="button" class="button choice" :disabled="iterationMode" :aria-pressed="initialization === 'scratch'"
                    @click="initialization = 'scratch'">从零训练</button>
                  <button type="button" class="button choice" :disabled="iterationMode" :aria-pressed="initialization === 'pretrained'"
                    @click="initialization = 'pretrained'">使用已有权重微调</button>
                </div>
              </div>
              <label class="field full-width">
                <span>基底模型 <b>*</b></span>
                <select v-model="draft.modelId" :disabled="iterationMode || !models.length" required>
                  <option value="" disabled>{{ optionsLoading ? '正在读取模型…' : '暂无匹配模型' }}</option>
                  <option v-for="model in models" :key="model.id" :value="model.id">{{ model.name }} · {{ model.architecture }}</option>
                </select>
                <small v-if="selectedModel?.sourceType === 'model_version'">来源：已登记模型版本 · {{ selectedModel.versionId }}</small>
                <small v-else-if="selectedModel?.sourceType === 'official_weights'">来源：Ultralytics 官方 YOLO11 · {{ selectedModel.pretrainingDataset }} 预训练 · 已下载至服务器</small>
                <small v-else-if="initialization === 'pretrained' && !models.length">暂无匹配权重。请准备本地预训练权重或登记一个训练模型版本。</small>
              </label>
            </div>
          </section>

          <section class="form-section" aria-labelledby="training-dataset">
            <h3 id="training-dataset"><span>02</span> 数据集与分集</h3>
            <div v-if="datasetsError" class="message error-row" role="alert">
              {{ datasetsError }}
              <button type="button" class="button" @click="loadDatasets">重试</button>
            </div>
            <label class="field">
              <span>训练数据集 <b>*</b></span>
              <select v-model="draft.datasetId" :disabled="iterationMode || datasetsLoading || !compatibleDatasets.length" required
                @change="submitError = ''">
                <option value="" disabled>
                  {{ datasetsLoading ? '正在读取数据集…' : compatibleDatasets.length ? '请选择匹配的数据集' : '暂无匹配数据集' }}
                </option>
                <option v-for="item in compatibleDatasets" :key="item.id" :value="item.id">{{ item.name }}</option>
              </select>
            </label>
            <template v-if="dataset">
              <div class="dataset-summary">
                <span>{{ splitSummary.total }} 张可用图片 · {{ dataset.classCount }} 个类别</span>
              </div>
              <p v-if="datasetError" class="dataset-error" role="status">{{ datasetError }}</p>
            </template>
            <div class="field-grid split-grid">
              <div class="field">
                <span>{{ iterationMode ? '固定清单的分集' : '已保存的分集' }}</span>
                <div class="split-bar" aria-hidden="true">
                  <span v-for="split in splitSummary.splits" :key="split.key" :class="split.key"
                    :style="{ width: split.percent + '%' }"></span>
                </div>
                <div class="split-legend">
                  <span v-for="split in splitSummary.splits" :key="split.key">
                    <i :class="split.key" aria-hidden="true"></i>{{ split.label }} {{ split.count }} 张
                    <small v-if="splitSummary.total">（{{ Math.round(split.percent) }}%）</small>
                  </span>
                </div>
              </div>
            </div>
            <div class="field">
              <span>数据增强预设</span>
              <div v-if="options?.augmentations.length" class="choice-grid" role="group" aria-label="数据增强预设">
                <button v-for="item in options.augmentations" :key="item.id" type="button" class="button choice option-card"
                  :aria-pressed="draft.augmentation === item.id" @click="draft.augmentation = item.id">
                  <strong>{{ item.name }}</strong><small>{{ item.description }}</small>
                </button>
              </div>
              <small v-else>暂无可用的增强预设。</small>
            </div>
          </section>

          <section class="form-section" aria-labelledby="training-hardware">
            <h3 id="training-hardware"><span>03</span> 算力与输入配置</h3>
            <div class="field">
              <span>计算设备 <b>*</b></span>
              <small v-if="deviceWarning">{{ deviceWarning }}</small>
              <small v-if="options?.workerStatus?.reason">{{ options.workerStatus.reason }}</small>
              <div v-if="options?.devices.length" class="field-grid" role="group" aria-label="计算设备">
                <button v-for="device in options.devices" :key="device.id" type="button" class="button choice option-card"
                  :aria-pressed="draft.deviceId === device.id" @click="draft.deviceId = device.id">
                  <strong>{{ device.name }}</strong>
                  <small>单任务运行，其余任务排队</small>
                  <small v-if="device.memoryBytes">显存 {{ (device.memoryBytes / 1024 ** 3).toFixed(1) }} GiB</small>
                </button>
              </div>
              <small v-else>暂无可选设备。</small>
            </div>
            <div class="field-grid">
              <label class="field">
                <span>批次大小（Batch Size）</span>
                <input v-model.number="draft.batchSize" type="number" min="1" max="1024" required>
              </label>
              <div class="field">
                <label for="training-image-size">输入尺寸（imgsz）</label>
                <input id="training-image-size" v-model.number="draft.imageSize" type="number" min="32" max="4096" step="32" required>
                <div class="quick-options" aria-label="输入尺寸常用值" role="group">
                  <button v-for="size in [320, 480, 640]" :key="size" type="button" class="button choice"
                    :aria-pressed="draft.imageSize === size" @click="draft.imageSize = size">{{ size }} × {{ size }}</button>
                </div>
              </div>
            </div>
            <label class="field">
              <span>训练轮数（Epochs）</span>
              <input v-model.number="draft.epochs" type="number" min="1" max="10000" required>
            </label>
          </section>

          <details class="form-section parameters">
            <summary>高级参数 · 优化器、冻结策略与复现</summary>
            <div class="field-grid parameter-grid">
              <label class="field">
                <span>优化器（Optimizer）</span>
                <select v-model="draft.optimizer" :disabled="!options?.optimizers.length" required>
                  <option value="" disabled>暂无可选优化器</option>
                  <option v-for="optimizer in options?.optimizers" :key="optimizer" :value="optimizer">{{ optimizer }}</option>
                </select>
              </label>
              <label class="field">
                <span>初始学习率（lr0）</span>
                <input v-model.number="draft.learningRate" type="number" min="0" max="1" step="any" required>
              </label>
              <label class="field">
                <span>最终学习率比例（lrf）</span>
                <input v-model.number="draft.finalLearningRate" type="number" min="0" max="1" step="any" required>
              </label>
              <label class="field">
                <span>冻结前 N 个模块（0 为不冻结）</span>
                <input v-model.number="draft.freeze" type="number" min="0" :disabled="!selectedModel?.pretrained" required>
                <small>仅对已有权重微调开放，模块范围由模型校验。</small>
              </label>
              <label class="field">
                <span>数据加载进程数（workers）</span>
                <input v-model.number="draft.workers" type="number" min="0" max="32" required>
              </label>
              <label class="field">
                <span>随机种子（Seed）</span>
                <input v-model.number="draft.seed" type="number" min="0" max="2147483647" required>
              </label>
            </div>
            <div class="switches">
              <label><input v-model="draft.amp" type="checkbox" :disabled="!isCuda"> 混合精度（AMP，仅 CUDA）</label>
              <label><input v-model="earlyStopping" type="checkbox" @change="updateEarlyStopping"> 启用早停</label>
              <label v-if="earlyStopping" class="patience">
                耐心轮数（Patience）
                <input v-model.number="draft.patience" type="number" min="1" max="10000" required>
              </label>
            </div>
            <small v-if="earlyStopping && draft.patience >= draft.epochs">耐心轮数不小于训练轮数，早停通常不会提前结束本次训练。</small>
          </details>
        </fieldset>
      </div>

      <footer class="dialog-footer">
        <p v-if="submitError" class="dataset-error" role="alert">{{ submitError }}</p>
        <small v-else-if="warnings.length" class="preflight-warnings" role="status">{{ warnings.join('；') }}</small>
        <small v-else>通过检查后，按已保存的分集生成训练快照。</small>
        <button type="button" class="button" :disabled="busy" @click="close">取消</button>
        <button type="submit" class="button primary" :disabled="!canSubmit">{{ busy ? '正在提交…' : warnings.length ? '继续创建' : '创建训练任务' }}</button>
      </footer>
    </form>
  </dialog>

  <dialog ref="nameWarning" class="name-warning" role="alertdialog" aria-labelledby="name-warning-title"
    aria-describedby="name-warning-message" @close="focusNameInput" @keydown.esc.stop.prevent="nameWarning?.close()">
    <form method="dialog">
      <h2 id="name-warning-title">训练任务名称重复</h2>
      <p id="name-warning-message">任务「{{ draft.name.trim() }}」已存在，请输入其他名称。</p>
      <button type="submit" class="button primary" autofocus>修改名称</button>
    </form>
  </dialog>
</template>

<style scoped>
.name-warning { width: min(440px, calc(100vw - 32px)); padding: 20px; border: 1px solid var(--line); border-radius: 10px; color: var(--text); background: var(--surface); }
.name-warning::backdrop { background: #29344944; }
.name-warning h2 { margin: 0; color: #83530e; font-size: 17px; }
.name-warning p { margin: 10px 0 16px; overflow-wrap: anywhere; }
.name-warning .button { display: block; margin-left: auto; }
.training-dialog {
  width: min(1040px, calc(100vw - 32px));
  max-height: calc(100dvh - 32px);
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 12px;
  color: var(--text);
  background: var(--surface);
  box-shadow: 0 20px 56px #18253736;
  overflow: hidden;
}
.training-dialog::backdrop { background: #29344977; backdrop-filter: blur(2px); }
.training-form { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; max-height: calc(100dvh - 34px); }
.dialog-header, .dialog-footer {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 22px;
  background: var(--soft);
}
.dialog-header { border-bottom: 1px solid var(--line); }
.header-icon { display: grid; place-items: center; width: 40px; height: 40px; flex: none; background: var(--primary); color: white; border-radius: 6px; }
.header-icon svg { width: 22px; height: 22px; }
.title-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.title-row h2 { margin: 0; font-size: 20px; }
.compute-badge { padding: 2px 7px; border: 1px solid var(--line); background: var(--selected); color: var(--primary); font-size: 12px; border-radius: 4px; }
.preflight-warnings { color: #83530e; }
.dialog-header p { margin: 2px 0 0; }
.dialog-header p, small { color: var(--muted); font-size: 12px; }
.close-button { margin-left: auto; min-width: 32px; padding-inline: 7px; font-size: 20px; flex: none; }
.dialog-content { overflow: auto; padding: 18px 22px; overscroll-behavior: contain; }
.form-fields { display: grid; gap: 20px; min-inline-size: 0; margin: 0; padding: 0; border: 0; }
.form-section { display: grid; gap: 10px; }
.form-section h3 { display: flex; align-items: center; gap: 8px; margin: 0; padding-bottom: 6px; border-bottom: 1px solid var(--line); font-size: 15px; }
.form-section h3 span { color: var(--primary); font: 600 13px Consolas, monospace; }
.field-grid, .choice-grid, .task-options { display: grid; gap: 8px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.basic-grid, .split-grid { grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); }
.choice-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.parameter-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.full-width { grid-column: 1 / -1; }
.field { display: grid; align-content: start; gap: 4px; min-width: 0; font-size: 13px; }
.field b { color: var(--danger); }
input:not([type='checkbox']), select {
  width: 100%;
  min-height: 34px;
  padding: 5px 8px;
  border: 1px solid #c7d1de;
  border-radius: 5px;
  background: var(--surface);
}
.choice[aria-pressed='true'] { background: var(--selected); border-color: var(--primary); color: #274563; }
.option-card { display: grid; gap: 3px; justify-content: start; align-content: center; text-align: start; min-height: 54px; padding-block: 8px; }
.option-card strong, .option-card small { overflow-wrap: anywhere; }
.dataset-summary, .error-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.dataset-summary { padding: 6px 8px; border: 1px solid var(--line); border-radius: 5px; background: var(--selected); font-size: 12px; }
.dataset-error { margin: 0; color: var(--danger); font-size: 13px; }
.split-bar { display: flex; height: 12px; background: var(--soft); border: 1px solid var(--line); border-radius: 4px; overflow: hidden; }
.split-legend { display: flex; flex-wrap: wrap; column-gap: 12px; row-gap: 3px; font-size: 12px; }
.split-legend i { display: inline-block; width: 8px; height: 8px; margin-right: 4px; border-radius: 2px; }
.train { background: #4f6885; }
.val { background: #83a6d0; }
.test { background: #acc9e8; }
.unassigned { background: #d5dce6; }
.quick-options, .switches { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.quick-options .button { min-height: 25px; padding: 3px 8px; font-size: 12px; }
.parameters { background: var(--soft); border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; }
.parameters summary { cursor: pointer; font-size: 14px; font-weight: 600; }
.parameters[open] > .field-grid { margin-top: 12px; }
.parameters .switches { margin-top: 10px; }
.switches { column-gap: 16px; font-size: 13px; }
.switches label { display: inline-flex; align-items: center; gap: 4px; }
.patience input { width: 75px; }
.message { margin: 0 0 12px; padding: 7px 10px; border: 1px solid var(--line); border-radius: 5px; background: var(--soft); }
.error-row { color: var(--danger); }
.dialog-footer { justify-content: flex-end; border-top: 1px solid var(--line); }
.dialog-footer p, .dialog-footer small { margin-right: auto; }
.dialog-footer .button { flex: none; }
@media (max-width: 660px) {
  .dialog-header, .dialog-content, .dialog-footer { padding-inline: 14px; }
  .basic-grid, .split-grid, .choice-grid { grid-template-columns: 1fr; }
  .parameter-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .dialog-footer { flex-wrap: wrap; }
  .dialog-footer p, .dialog-footer small { flex-basis: 100%; }
}
@media (max-width: 380px) {
  .field-grid { grid-template-columns: 1fr; }
  .title-row h2 { font-size: 17px; }
  .dataset-summary { align-items: flex-start; flex-direction: column; }
}
</style>
