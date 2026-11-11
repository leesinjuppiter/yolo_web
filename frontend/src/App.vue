<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AnnotationView from './AnnotationView.vue'
import DatasetDialogs from './DatasetDialogs.vue'
import DatasetExchangeDialog from './components/DatasetExchangeDialog.vue'
import DatasetExcludedImagesDialog from './components/DatasetExcludedImagesDialog.vue'
import SimilarityReviewDialog from './components/SimilarityReviewDialog.vue'
import CreateTrainingDialog from './components/training/CreateTrainingDialog.vue'
import DatasetsView from './DatasetsView.vue'
import TrainingView from './pages/TrainingView.vue'
import TrainingDetailView from './pages/TrainingDetailView.vue'
import { getTraining } from './api/training'
import type { ModelVersion } from './types/models'
import { createDataset, deleteDataset, deleteDatasetImage, getDataset, listDatasets, readReportSnapshot, refreshReportSnapshot, saveSimilarityReview, saveSplits, updateAnnotations, updateDatasetClass, uploadImages } from './api/datasets'
import type { Annotation, AnnotationStatus, Dataset, DatasetAction, DatasetClass, DatasetImage, DatasetReport, DialogKind, ReportIssue, ReportKind, ReportSnapshot, SelectableDatasetTask, SimilarityDecision, Split } from './domain'
import type { TrainingConfig } from './types/training'

const ModelRegistryView = defineAsyncComponent(() => import('./pages/ModelRegistryView.vue'))
const ModelCompareView = defineAsyncComponent(() => import('./pages/ModelCompareView.vue'))
const DeploymentCenterView = defineAsyncComponent(() => import('./pages/DeploymentCenterView.vue'))

const route = useRoute()
const router = useRouter()
const inTraining = computed(() => route.name === 'training' || route.name === 'training-detail')
const inDatasets = computed(() => route.name === 'datasets' || route.name === 'annotation')
const activeSection = computed(() => inTraining.value ? 'training' : route.name === 'model-compare' ? 'models' : String(route.name))
const sectionTitle = computed(() => activeSection.value === 'training' ? '模型训练' : activeSection.value === 'models' ? '模型仓库' : activeSection.value === 'deployments' ? '部署中心' : '数据集管理')
const trainingDraft = ref<{ datasetId?: string; config?: TrainingConfig }>()
const trainingDatasetsRevision = ref(0)
watch(inTraining, visible => { if (!visible) trainingDraft.value = undefined })
const datasets = ref<Dataset[]>([])
const loaded = ref(false)
const loadingError = ref('')
const dialog = ref<DialogKind | null>(null)
const dialogTarget = ref('')
const dialogDataset = computed(() => datasets.value.find(item => item.id === dialogTarget.value))
const activeDataset = computed(() => datasets.value.find(item => item.id === route.params.id))
const initialImageId = computed(() => typeof route.query.image === 'string' ? route.query.image : undefined)
const annotation = ref<{ confirmLeave: () => boolean | Promise<boolean> }>()
const report = ref<DatasetReport>()
type ReviewGroup = { images: [DatasetImage, DatasetImage]; issue: ReportIssue; decision?: SimilarityDecision }
const review = ref<{ datasetId: string; datasetName: string; groups: ReviewGroup[]; index: number; generatedAt: string | null; confirmed: boolean; continuing: boolean }>()
const reviewGroup = computed(() => review.value?.groups[review.value.index])
const reviewResult = computed(() => {
  const group = reviewGroup.value
  switch (group?.decision) {
    case 'keep_both': return '已确认重复，两张图均已保留'
    case 'discard_image': return `已排除「${group.images[0].name}」`
    case 'discard_related': return `已排除「${group.images[1].name}」`
    default: return ''
  }
})
const reviewBusy = ref(false)
const reviewError = ref('')
const reviewFeedback = ref('')
const excludedDatasetId = ref('')
const excludedDataset = computed(() => datasets.value.find(item => item.id === excludedDatasetId.value))
const reviewable = computed(() => {
  const current = review.value
  const snapshot = report.value
  const issue = reviewGroup.value?.issue
  return Boolean(current && !reviewGroup.value?.decision && issue?.code === 'duplicate_exact' && issue.review_status === 'pending'
    && issue.image_sha256 && issue.related_image_sha256
    && snapshot?.kind === 'duplicates' && snapshot.datasetId === current.datasetId
    && (current.continuing || (snapshot.status === 'ready' && !snapshot.stale)))
})
const busy = ref(false)
const dialogError = ref('')
const annotationError = ref('')
const notice = ref('')
let noticeTimer: ReturnType<typeof setTimeout> | undefined
let reportPoll: ReturnType<typeof setTimeout> | undefined
let reportController: AbortController | undefined

const sections = [
  { label: '数据集', route: 'datasets', icon: 'M4 10h16v10H4z M4 10l2-4h12l2 4M8 14h8' },
  { label: '模型训练', route: 'training', icon: 'M4 20V9m5 11V4m6 16v-7m5 7V7' },
  { label: '模型仓库', route: 'models', icon: 'M12 2l9 5v10l-9 5-9-5V7z M3 7l9 5 9-5 M12 12v10' },
  { label: '部署中心', route: 'deployments', icon: 'M4 4h16v5H4z M4 15h16v5H4z M8 9v6m8-6v6' },
  { label: '智能体', icon: 'M5 8h14v11H5z M12 8V4 M8 13h2m4 0h2' },
  { label: '审计日志', icon: 'M5 3h14v18H5z M8 8h8m-8 4h8m-8 4h5' },
  { label: '系统设置', icon: 'M4 6h16m-16 6h16m-16 6h16 M8 4v4m8 2v4m-6 2v4' },
]
const navigation = [
  { label: '工作空间', sections: sections.slice(0, 5) },
  { label: '治理与运维', sections: sections.slice(5) },
]

function message(error: unknown) {
  return error instanceof Error ? error.message : '操作未完成，请重试'
}

function showNotice(value: string) {
  notice.value = value
  clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { notice.value = '' }, 5500)
}

async function initialize() {
  loaded.value = false
  loadingError.value = ''
  try {
    datasets.value = await listDatasets()
  } catch (error) {
    loadingError.value = message(error)
  } finally {
    loaded.value = true
  }
}

onMounted(async () => { await router.isReady(); if (inDatasets.value) void initialize() })
watch(inDatasets, visible => { if (visible && !loaded.value) void initialize() })
onUnmounted(() => clearTimeout(noticeTimer))
onUnmounted(stopReportSync)

const stopGuard = router.beforeEach((to, from) => {
  if (from.name === 'annotation' && to.fullPath !== from.fullPath) {
    if (busy.value) return false
    return annotation.value?.confirmLeave() ?? true
  }
  return true
})
onUnmounted(stopGuard)

function openDialog(kind: DialogKind, dataset?: Dataset) {
  dialogError.value = ''
  dialogTarget.value = dataset?.id ?? ''
  dialog.value = kind
}

async function openTrainingDraft(datasetId?: string) {
  if (!inTraining.value) await router.push({ name: 'training' })
  if (inTraining.value) trainingDraft.value = { datasetId }
}

function retrain(config: TrainingConfig) {
  trainingDraft.value = { datasetId: config.datasetId, config: { ...config, name: '' } }
}

async function finetuneRegisteredModel(model: ModelVersion) {
  try {
    const task = await getTraining(model.taskId)
    await router.push({ name: 'training' })
    trainingDraft.value = { datasetId: task.config.datasetId, config: { ...task.config, name: '', modelId: `version:${model.id}` } }
  } catch (error) {
    showNotice(message(error))
  }
}

function openTrainingTask(id: string, tab?: 'logs') {
  trainingDraft.value = undefined
  void router.push({ name: 'training-detail', params: { taskId: id }, query: tab ? { tab } : {} })
}

function closeDialog() {
  if (!busy.value) dialog.value = null
}

function stopReportSync() {
  clearTimeout(reportPoll)
  reportController?.abort()
  reportController = undefined
}

function closeReport() {
  stopReportSync()
  report.value = undefined
}

function showReport(kind: ReportKind, dataset: Dataset) {
  if (report.value?.datasetId === dataset.id && report.value.kind === kind) {
    closeReport()
    return
  }
  report.value = { kind, datasetId: dataset.id, pending: true, status: 'loading', stale: false,
    generatedAt: null, progress: null, error: null }
  syncReport()
}

function applyReportSnapshot(datasetId: string, kind: ReportKind, snapshot: ReportSnapshot) {
  report.value = { ...snapshot.report, kind, datasetId, status: snapshot.status,
    pending: snapshot.status === 'queued' || snapshot.status === 'running',
    stale: snapshot.stale, generatedAt: snapshot.generated_at, progress: snapshot.progress, error: snapshot.error }
  if (kind === 'duplicates' && snapshot.status === 'ready' && !snapshot.stale) {
    refreshReviewGroups(datasetId, snapshot)
  }
}

async function updateReport(datasetId: string, kind: ReportKind, signal: AbortSignal, action: 'open' | 'poll' | 'refresh') {
  try {
    let snapshot = action === 'refresh'
      ? await refreshReportSnapshot(datasetId, kind, true, signal)
      : await readReportSnapshot(datasetId, kind, signal)
    if (signal.aborted) return
    applyReportSnapshot(datasetId, kind, snapshot)
    if (action === 'open' && (snapshot.status === 'idle' || snapshot.status === 'queued'
        || (snapshot.status === 'ready' && snapshot.stale))) {
      snapshot = await refreshReportSnapshot(datasetId, kind, false, signal)
      if (signal.aborted) return
      applyReportSnapshot(datasetId, kind, snapshot)
    }
    if (snapshot.status === 'queued' || snapshot.status === 'running') {
      reportPoll = setTimeout(() => { void updateReport(datasetId, kind, signal, 'poll') }, 1000)
    }
  } catch (error) {
    if (!signal.aborted && report.value) {
      report.value = { ...report.value, pending: false, status: 'failed', error: message(error) }
    }
  }
}

function syncReport(force = false, action: 'open' | 'poll' = 'open') {
  const current = report.value
  if (!current) return
  stopReportSync()
  reportController = new AbortController()
  report.value = { ...current, pending: true, status: 'loading', error: null }
  void updateReport(current.datasetId, current.kind, reportController.signal, force ? 'refresh' : action)
}

function openAnnotation(dataset: Dataset, imageId?: string) {
  if (imageId && !dataset.images.some(item => item.id === imageId)) {
    showNotice('当前数据集中已找不到报告中的图片，请刷新报告。')
    return
  }
  annotationError.value = ''
  void router.push({ name: 'annotation', params: { id: dataset.id }, query: imageId ? { image: imageId } : {} })
}

function buildReviewGroups(dataset: Dataset, issues: ReportIssue[]): ReviewGroup[] {
  const images = new Map(dataset.images.map(image => [image.id, image]))
  return issues.flatMap<ReviewGroup>(item => {
    const first = images.get(item.image_id ?? '')
    const second = images.get(item.related_image_id ?? '')
    return first && second ? [{ images: [first, second], issue: item }] : []
  })
}

function refreshReviewGroups(datasetId: string, snapshot: ReportSnapshot) {
  const current = review.value
  const group = reviewGroup.value
  if (current?.datasetId !== datasetId || !group || reviewBusy.value || current.generatedAt === snapshot.generated_at) return
  const dataset = datasets.value.find(item => item.id === datasetId)
  if (!dataset) return
  const issues = (snapshot.report?.issues ?? []).filter(item => (item.review_status === 'confirmed') === current.confirmed)
  const groups = buildReviewGroups(dataset, issues)
  const same = groups.findIndex(({ issue }) => issue.image_id === group.issue.image_id
    && issue.related_image_id === group.issue.related_image_id)
  const next = same >= 0 ? same : group.decision ? nextPendingGroup(groups, current.index) : -1
  if (next >= 0) {
    if (same < 0) reviewFeedback.value = '审核已保存，已进入下一组。'
    review.value = { ...current, groups, index: next, generatedAt: snapshot.generated_at }
  } else if (!group.decision) {
    const index = Math.min(current.index, groups.length)
    groups.splice(index, 0, { ...group, issue: { ...group.issue, review_status: null } })
    review.value = { ...current, groups, index, generatedAt: snapshot.generated_at }
  } else {
    review.value = { ...current, groups: [group], index: 0, generatedAt: snapshot.generated_at }
  }
}

function openSimilarityReview(dataset: Dataset, issue: ReportIssue, issues: ReportIssue[]) {
  const groups = buildReviewGroups(dataset, issues)
  const index = groups.findIndex(group => group.issue === issue)
  if (index < 0) {
    showNotice('当前数据集中已找不到完整的图片对，请刷新报告。')
    return
  }
  reviewError.value = ''
  reviewFeedback.value = ''
  review.value = { datasetId: dataset.id, datasetName: dataset.name, groups, index,
    generatedAt: report.value?.generatedAt ?? null, confirmed: issue.review_status === 'confirmed', continuing: false }
}

function nextPendingGroup(groups: ReviewGroup[], start: number) {
  const next = groups.findIndex((group, index) => index >= start && group.issue.review_status === 'pending')
  return next >= 0 ? next : groups.findIndex(group => group.issue.review_status === 'pending')
}

function stepReview(offset: -1 | 1) {
  const current = review.value
  if (!current || reviewBusy.value || !current.groups[current.index + offset]) return
  reviewError.value = ''
  reviewFeedback.value = ''
  current.index += offset
}

async function submitReview(decision: SimilarityDecision) {
  const current = review.value
  const group = reviewGroup.value
  const firstSha = group?.issue.image_sha256
  const secondSha = group?.issue.related_image_sha256
  if (!current || !group || !reviewable.value || reviewBusy.value || !firstSha || !secondSha) return
  const [first, second] = group.images
  reviewBusy.value = true
  reviewError.value = ''
  reviewFeedback.value = ''
  try {
    await saveSimilarityReview(current.datasetId, { image_id: first.id, related_image_id: second.id,
      image_sha256: firstSha, related_image_sha256: secondSha, decision })
    group.decision = decision
    const discarded = decision === 'discard_image' ? first : decision === 'discard_related' ? second : undefined
    const available = (item: ReviewGroup) => !item.decision && (!discarded || !item.images.some(image => image.id === discarded.id))
    const groups = current.groups.filter(available)
    const next = nextPendingGroup(groups, current.groups.slice(0, current.index).filter(available).length)
    review.value = { ...current, groups: next >= 0 ? groups : [group], index: Math.max(0, next), continuing: true }
    if (next >= 0) reviewFeedback.value = '审核已保存，已进入下一组。'
    const dataset = datasets.value.find(item => item.id === current.datasetId)
    if (discarded && dataset) {
      replaceDataset({ ...dataset, images: dataset.images.filter(item => item.id !== discarded.id) }, 'poll')
      showNotice(`已排除「${discarded.name}」，可在「已排除样本」中恢复。`)
    } else {
      if (report.value?.datasetId === current.datasetId) syncReport(false, 'poll')
      showNotice('审核结果已保存。')
    }
  } catch (error) {
    reviewError.value = message(error)
    if (report.value?.datasetId === current.datasetId) syncReport(false, 'poll')
  } finally {
    reviewBusy.value = false
  }
}

function restoreIntoDataset(image: DatasetImage) {
  const dataset = excludedDataset.value
  if (!dataset) return
  replaceDataset({ ...dataset, images: [...dataset.images.filter(item => item.id !== image.id), image] })
  showNotice(`已恢复「${image.name}」。`)
}

function datasetAction(action: DatasetAction, dataset: Dataset) {
  switch (action) {
    case 'annotate':
      if (dataset.images.length) openAnnotation(dataset)
      else showNotice('请先添加可标注的图片')
      break
    case 'validate':
    case 'duplicates':
    case 'quality':
      showReport(action, dataset)
      break
    case 'train':
      void openTrainingDraft(dataset.id)
      break
    case 'assistant':
      showNotice('当前版本开放数据集与标注功能')
      break
    case 'excluded':
      excludedDatasetId.value = dataset.id
      break
    default:
      openDialog(action, dataset)
  }
}

function replaceDataset(record: Dataset, reportAction: 'open' | 'poll' = 'open') {
  datasets.value = datasets.value.map(item => item.id === record.id ? record : item)
  trainingDatasetsRevision.value += 1
  if (report.value?.datasetId !== record.id) return
  if (route.name === 'datasets') syncReport(false, reportAction)
  else closeReport()
}

async function dialogMutation(operation: () => Promise<string>) {
  if (busy.value) return
  busy.value = true
  dialogError.value = ''
  try {
    const result = await operation()
    dialog.value = null
    showNotice(result)
  } catch (error) {
    dialogError.value = message(error)
  } finally {
    busy.value = false
  }
}

function addDataset(dataset: Dataset) {
  datasets.value = [dataset, ...datasets.value]
}

function create(name: string, task: SelectableDatasetTask) {
  void dialogMutation(async () => {
    addDataset(await createDataset(name, task))
    return '数据集已创建，可以添加图片'
  })
}

function add(files: File[], split: Split | null) {
  const dataset = dialogDataset.value
  if (!dataset || !files.length) return
  void dialogMutation(async () => {
    replaceDataset(await uploadImages(dataset.id, files, split))
    return '已添加 ' + files.length + ' 张图片'
  })
}

function changeSplits(splits: Record<string, Split | null>) {
  const dataset = dialogDataset.value
  if (!dataset) return
  void dialogMutation(async () => {
    replaceDataset(await saveSplits(dataset.id, splits))
    return '分集已保存'
  })
}

function deleteCurrent() {
  const dataset = dialogDataset.value
  if (!dataset) return
  void dialogMutation(async () => {
    await deleteDataset(dataset.id)
    datasets.value = datasets.value.filter(item => item.id !== dataset.id)
    if (report.value?.datasetId === dataset.id) closeReport()
    return '已删除数据集「' + dataset.name + '」'
  })
}

async function saveAnnotations(imageId: string, annotations: Annotation[], classes: DatasetClass[], status: AnnotationStatus) {
  const dataset = activeDataset.value
  if (busy.value || !dataset) return false
  const index = dataset.images.findIndex(item => item.id === imageId)
  if (index < 0) return false
  busy.value = true
  annotationError.value = ''
  try {
    const saved = await updateAnnotations(dataset.id, dataset.images[index], annotations, classes, status)
    const images = dataset.images.slice()
    images[index] = saved.image
    replaceDataset({ ...dataset, images, classes: saved.classes })
    return true
  } catch (error) {
    annotationError.value = message(error)
    return false
  } finally {
    busy.value = false
  }
}

async function editClass(entry: DatasetClass, name: string, color: string) {
  const dataset = activeDataset.value
  if (busy.value || !dataset) throw new Error('当前无法修改类别，请稍后重试。')
  busy.value = true
  try {
    const saved = await updateDatasetClass(dataset.id, entry, name, color)
    replaceDataset({ ...dataset, classes: dataset.classes.map(item => item.id === saved.id ? saved : item) })
    return saved
  } finally {
    busy.value = false
  }
}

async function deleteImage(imageId: string) {
  const dataset = activeDataset.value
  if (busy.value || !dataset?.images.some(item => item.id === imageId)) return false
  busy.value = true
  annotationError.value = ''
  try {
    await deleteDatasetImage(dataset.id, imageId)
    replaceDataset({ ...dataset, images: dataset.images.filter(item => item.id !== imageId) })
    showNotice('图片已删除')
    return true
  } catch (error) {
    annotationError.value = message(error)
    return false
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-show="route.name !== 'annotation'" class="app-shell">
    <aside class="workbench-nav">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <rect x="4" y="4" width="6" height="6" rx="1.5"/>
            <rect x="14" y="4" width="6" height="6" rx="1.5"/>
            <rect x="4" y="14" width="6" height="6" rx="1.5"/>
            <rect x="14" y="14" width="6" height="6" rx="1.5"/>
          </svg>
        </span>
        <div>
          <strong>检测系统工作台</strong>
          <small>OPTI-METRIX</small>
        </div>
      </div>
      <nav aria-label="工作台导航">
        <div v-for="group in navigation" :key="group.label" class="workbench-nav-group">
          <div class="workspace-caption">{{ group.label }}</div>
          <button
            v-for="section in group.sections"
            :key="section.label"
            type="button"
            :class="{ active: section.route === activeSection }"
            :aria-current="section.route === activeSection ? 'page' : undefined"
            :disabled="!section.route"
            :title="section.route ? '' : '该模块尚未开放'"
            @click="section.route && router.push({ name: section.route })"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path :d="section.icon"/></svg>
            {{ section.label }}
            <span v-if="section.route === 'datasets' && loaded && !loadingError" class="workspace-count">{{ datasets.length }}</span>
          </button>
        </div>
      </nav>
      <div class="workbench-status">
        <strong><span v-if="inDatasets" :class="{ ready: loaded && !loadingError }" aria-hidden="true"></span>{{ sectionTitle }}</strong>
        <small>{{ !inDatasets ? '执行与验证状态以任务报告为准' : !loaded ? '正在连接本地标注服务' : loadingError ? '本地标注服务连接异常' : '数据与标注保存在本地设备' }}</small>
      </div>
    </aside>
    <div class="workbench-body">
      <header class="workbench-top">
        <div class="workbench-location">
          <span class="workbench-parent">检测工作台</span><span class="workbench-parent" aria-hidden="true">/</span>
          <strong>{{ sectionTitle }}</strong>
          <span class="workbench-local" :class="{ 'workbench-training-mode': inTraining }">
            {{ inTraining ? '训练配置与监控' : inDatasets ? '本地标注服务' : activeSection === 'models' ? '版本与验证' : 'ONNX FP32 部署包' }}
          </span>
        </div>
        <div v-if="inTraining" class="workbench-actions">
          <button class="button primary" type="button" @click="openTrainingDraft()">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
            新建训练任务
          </button>
        </div>
        <div v-else-if="inDatasets && loaded && !loadingError" class="workbench-actions">
          <button class="button" type="button" @click="openDialog('import')">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V4m-4 4 4-4 4 4M4 15v5h16v-5"/></svg>
            导入数据集
          </button>
          <button class="button primary" type="button" @click="openDialog('create')">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
            新建数据集
          </button>
        </div>
      </header>
      <main class="workbench-main">
        <KeepAlive>
          <TrainingView v-if="route.name === 'training'" @open="openTrainingTask" @retrain="retrain" @create="openTrainingDraft()" />
        </KeepAlive>
        <KeepAlive><ModelRegistryView v-if="route.name === 'models'" @finetune="finetuneRegisteredModel" /></KeepAlive>
        <KeepAlive><ModelCompareView v-if="route.name === 'model-compare'" /></KeepAlive>
        <KeepAlive><DeploymentCenterView v-if="route.name === 'deployments'" /></KeepAlive>
        <TrainingDetailView
          v-if="route.name === 'training-detail'"
          :task-id="String(route.params.taskId)"
          :initial-tab="route.query.tab === 'logs' ? 'logs' : undefined"
          @back="router.push({ name: 'training' })"
          @retrain="retrain"
          @open-task="openTrainingTask"
        />
        <div v-show="inDatasets">
          <div v-if="!loaded" class="page-state" role="status">正在读取数据集…</div>
          <div v-else-if="loadingError" class="page-state" role="alert">
            <p>{{ loadingError }}</p><button class="button" @click="initialize">重试</button>
          </div>
          <DatasetsView
            v-else
            :datasets="datasets"
            :report="report"
            @create="openDialog('create')"
            @action="datasetAction"
            @close-report="closeReport"
            @refresh-report="syncReport(true)"
            @open-image="openAnnotation"
            @review-pair="openSimilarityReview"
          />
        </div>
      </main>
    </div>
  </div>
  <template v-if="route.name === 'annotation'">
    <AnnotationView
      v-if="activeDataset"
      :key="activeDataset.id"
      ref="annotation"
      :dataset="activeDataset"
      :initial-image-id="initialImageId"
      :busy="busy"
      :error="annotationError"
      :save-annotations="saveAnnotations"
      :edit-class="editClass"
      :delete-image="deleteImage"
      @back="router.push({ name: 'datasets' })"
    />
    <div v-else class="page-state">
      <p>{{ loaded ? (loadingError || '未找到可编辑的数据集') : '正在读取数据集…' }}</p>
      <button v-if="loaded" class="button" @click="router.push({ name: 'datasets' })">返回数据集</button>
    </div>
  </template>
  <CreateTrainingDialog
    v-if="inTraining && trainingDraft"
    :datasets-revision="trainingDatasetsRevision"
    :dataset-id="trainingDraft.datasetId"
    :initial-config="trainingDraft.config"
    @close="trainingDraft = undefined"
    @created="openTrainingTask"
  />
  <DatasetExchangeDialog
    v-if="dialog === 'import' || dialog === 'export'"
    :initial-mode="dialog"
    :dataset="dialogDataset"
    :datasets="datasets"
    @close="closeDialog"
    @imported="addDataset"
  />
  <DatasetDialogs
    v-else
    :kind="dialog"
    :dataset="dialogDataset"
    :busy="busy"
    :error="dialogError"
    @close="closeDialog"
    @create="create"
    @add="add"
    @splits="changeSplits"
    @delete="deleteCurrent"
    @notice="showNotice"
  />
  <SimilarityReviewDialog
    v-if="review && reviewGroup"
    :dataset-name="review.datasetName"
    :images="reviewGroup.images"
    :fingerprints="[reviewGroup.issue.image_sha256, reviewGroup.issue.related_image_sha256]"
    :group-index="review.index"
    :group-count="review.groups.length"
    :reviewable="reviewable"
    :confirmed="reviewGroup.issue.review_status === 'confirmed' || reviewGroup.decision === 'keep_both'"
    :busy="reviewBusy"
    :error="reviewError"
    :feedback="reviewFeedback"
    :result="reviewResult"
    :refreshing="!!reviewResult && !!report?.pending"
    :refresh-error="report?.status === 'failed' ? report.error : null"
    @close="review = undefined"
    @refresh="syncReport(true)"
    @step="stepReview"
    @submit="submitReview"
  />
  <DatasetExcludedImagesDialog
    v-if="excludedDataset"
    :dataset="excludedDataset"
    @close="excludedDatasetId = ''"
    @restored="restoreIntoDataset"
  />
  <div v-if="notice" class="workbench-notice" role="status">
    {{ notice }} <button type="button" aria-label="关闭提示" @click="notice = ''">×</button>
  </div>
</template>
