<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AnnotationView from './AnnotationView.vue'
import DatasetDialogs from './DatasetDialogs.vue'
import DatasetExchangeDialog from './components/DatasetExchangeDialog.vue'
import DatasetsView from './DatasetsView.vue'
import { createDataset, deleteDataset, deleteDatasetImage, listDatasets, readReport, saveSplits, updateAnnotations, updateDatasetClass, uploadImages } from './api/datasets'
import type { Annotation, AnnotationStatus, Dataset, DatasetAction, DatasetClass, DatasetReport, DialogKind, ReportKind, Split, TaskType } from './domain'

const route = useRoute()
const router = useRouter()
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
const busy = ref(false)
const dialogError = ref('')
const annotationError = ref('')
const notice = ref('')
let noticeTimer: ReturnType<typeof setTimeout> | undefined
let reportRequest = 0

const sections = [
  { label: '数据集', icon: 'M3 5h18v14H3z M3 15l5-5 4 4 3-3 6 5' },
  { label: '模型训练', icon: 'M4 20V9m5 11V4m6 16v-7m5 7V7' },
  { label: '模型仓库', icon: 'M12 2l9 5v10l-9 5-9-5V7z M3 7l9 5 9-5 M12 12v10' },
  { label: '智能体', icon: 'M5 8h14v11H5z M12 8V4 M8 13h2m4 0h2' },
  { label: '审计日志', icon: 'M5 3h14v18H5z M8 8h8m-8 4h8m-8 4h5' },
  { label: '系统设置', icon: 'M4 6h16m-16 6h16m-16 6h16 M8 4v4m8 2v4m-6 2v4' },
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

onMounted(initialize)
onUnmounted(() => clearTimeout(noticeTimer))

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

function closeDialog() {
  if (!busy.value) dialog.value = null
}

function closeReport() {
  reportRequest += 1
  report.value = undefined
}

async function showReport(kind: ReportKind, dataset: Dataset) {
  if (report.value?.datasetId === dataset.id && report.value.kind === kind) {
    closeReport()
    return
  }
  const request = ++reportRequest
  report.value = { kind, datasetId: dataset.id, pending: true }
  try {
    const result = await readReport(dataset.id, kind)
    if (request === reportRequest) report.value = { ...result, kind, datasetId: dataset.id, pending: false }
  } catch (error) {
    if (request === reportRequest) {
      report.value = { kind, datasetId: dataset.id, pending: false, title: '检查未完成', messages: [message(error)] }
    }
  }
}

function openAnnotation(dataset: Dataset, imageId?: string) {
  annotationError.value = ''
  void router.push({ name: 'annotation', params: { id: dataset.id }, query: imageId ? { image: imageId } : {} })
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
      void showReport(action, dataset)
      break
    case 'train':
      showNotice('当前版本开放数据集与标注功能')
      break
    case 'assistant':
      showNotice('当前版本开放数据集与标注功能')
      break
    default:
      openDialog(action, dataset)
  }
}

function replaceDataset(record: Dataset) {
  datasets.value = datasets.value.map(item => item.id === record.id ? record : item)
  if (report.value?.datasetId === record.id) closeReport()
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

function create(name: string, task: TaskType, keypointNames: string[]) {
  void dialogMutation(async () => {
    addDataset(await createDataset(name, task, keypointNames))
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
  const image = dataset?.images.find(item => item.id === imageId)
  if (busy.value || !dataset || !image) return false
  busy.value = true
  annotationError.value = ''
  try {
    replaceDataset(await updateAnnotations(dataset.id, image, annotations, classes, status))
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
            <path d="M4 9V4h5m6 0h5v5m0 6v5h-5m-6 0H4v-5m4-3h8m-4-4v8"/>
          </svg>
        </span>
        <strong>检测系统工作台</strong>
      </div>
      <div class="workspace-caption">工作区</div>
      <nav aria-label="工作台导航">
        <button
          v-for="(section, index) in sections"
          :key="section.label"
          type="button"
          :class="{ active: index === 0 }"
          :aria-current="index === 0 ? 'page' : undefined"
          :disabled="index !== 0"
          :title="index === 0 ? '' : '此版本开放数据集模块'"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path :d="section.icon"/></svg>
          {{ section.label }}
        </button>
      </nav>
      <div class="workbench-status"><span aria-hidden="true"></span>本地工作台</div>
    </aside>
    <div class="workbench-body">
      <header class="workbench-top"><strong>数据集管理</strong><span>本地标注服务</span></header>
      <main class="workbench-main">
        <div v-if="!loaded" class="page-state" role="status">正在读取数据集…</div>
        <div v-else-if="loadingError" class="page-state" role="alert">
          <p>{{ loadingError }}</p><button class="button" @click="initialize">重试</button>
        </div>
        <DatasetsView
          v-else
          :datasets="datasets"
          :report="report"
          @create="openDialog('create')"
          @import="openDialog('import')"
          @action="datasetAction"
          @close-report="closeReport"
          @open-image="openAnnotation"
        />
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
  <div v-if="notice" class="workbench-notice" role="status">
    {{ notice }} <button type="button" aria-label="关闭提示" @click="notice = ''">×</button>
  </div>
</template>
