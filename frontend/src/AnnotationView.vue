<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { taskLabels, type Annotation, type AnnotationStatus, type Dataset, type DatasetClass, type DatasetImage } from './domain'
import AnnotationCanvas, { type AnnotationTool } from './annotation/AnnotationCanvas.vue'
import { createUuid } from './utils/id'

const props = defineProps<{
  dataset: Dataset
  initialImageId?: string
  busy?: boolean
  error?: string
  saveAnnotations: (imageId: string, annotations: Annotation[], classes: DatasetClass[], status: AnnotationStatus) => Promise<boolean>
  editClass: (entry: DatasetClass, name: string, color: string) => Promise<DatasetClass>
  deleteImage: (imageId: string) => Promise<boolean>
}>()
const emit = defineEmits<{ back: [] }>()

type Filter = 'all' | 'train' | 'val' | 'test' | 'unassigned'
const filters: { value: Filter; label: string }[] = [
  { value: 'all', label: '全部' }, { value: 'train', label: 'train' }, { value: 'val', label: 'val' },
  { value: 'test', label: 'test' }, { value: 'unassigned', label: '未分集' },
]
const statusText: Record<AnnotationStatus, string> = { unlabeled: '未标注', negative: '负样本', annotated: '已标注' }
const colors = ['#0b83b8', '#6052dc', '#bc650f', '#13795b', '#b34a77', '#7542a6']
const visibility: { value: 0 | 1 | 2; label: string }[] = [
  { value: 0, label: '未标记' }, { value: 1, label: '遮挡' }, { value: 2, label: '可见' },
]

const split = ref<Filter>('all')
const imageId = ref('')
const annotations = ref<Annotation[]>([])
const classes = ref<DatasetClass[]>([])
const negative = ref(false)
const activeClassId = ref('')
const selectedId = ref('')
const activeVertex = ref<number>()
const activeKeypoint = ref('')
const activeVisibility = ref<1 | 2>(2)
const tool = ref<AnnotationTool>('select')
const zoom = ref(1)
const grid = ref(true)
const hiddenAnnotationIds = ref(new Set<string>())
const draftPoints = ref(0)
const classForm = ref<{ entry?: DatasetClass; name: string; color: string }>()
const classError = ref('')
const classInput = ref<HTMLInputElement>()
const canvas = ref<InstanceType<typeof AnnotationCanvas>>()
const dialog = ref<HTMLDialogElement>()
const dialogMode = ref<'discard' | 'negative' | 'delete-image'>('discard')
const deleteTarget = ref<DatasetImage>()
const baseline = ref('')
const switchingView = ref(false)
const unfinishedNotice = ref(false)
let confirmResult: ((confirmed: boolean) => void) | undefined

const images = computed(() => props.dataset.images.filter(image => split.value === 'all' || (image.split ?? 'unassigned') === split.value))
const image = computed(() => props.dataset.images.find(item => item.id === imageId.value))
const imageIndex = computed(() => images.value.findIndex(item => item.id === imageId.value))
const selected = computed(() => annotations.value.find(item => item.id === selectedId.value))
const selectedHidden = computed(() => hiddenAnnotationIds.value.has(selectedId.value))
const polygonSelection = computed(() => !selectedHidden.value && selected.value?.type === 'polygon' ? selected.value : undefined)
const pose = computed(() => selected.value?.type === 'pose' ? selected.value : undefined)
const byClass = computed(() => new Map(classes.value.map(item => [item.id, item])))
const status = computed<AnnotationStatus>(() => annotations.value.length ? 'annotated' : negative.value ? 'negative' : 'unlabeled')
const drawLabel = computed(() => ({
  detect: '矩形框', segment: '多边形', obb: '旋转框', classify: '分类', pose: '目标框',
})[props.dataset.task])
const canDraw = computed(() => !!image.value?.src && !!activeClassId.value && !props.busy && props.dataset.task !== 'classify')

function snapshot(items: Annotation[], labels: DatasetClass[], value: AnnotationStatus) {
  const rect = ({ x, y, width, height }: { x: number; y: number; width: number; height: number }) => [x, y, width, height]
  return JSON.stringify([value, labels.map(({ id, name, color }) => [id, name, color]), items.map(item => {
    const base = [item.id, item.class_id, item.source, item.type]
    switch (item.type) {
      case 'bbox': return [...base, rect(item.bbox)]
      case 'obb': return [...base, item.obb.cx, item.obb.cy, item.obb.width, item.obb.height, item.obb.angle]
      case 'polygon': return [...base, item.polygon]
      case 'pose': return [...base, rect(item.bbox), item.keypoints.map(({ name, x, y, visible }) => [name, x, y, visible])]
      case 'classify': return base
    }
  })])
}

const dirty = computed(() => draftPoints.value > 0 || snapshot(annotations.value, classes.value, status.value) !== baseline.value)

function firstImage() {
  return props.dataset.images.find(item => item.id === props.initialImageId)
    ?? props.dataset.images.find(item => item.status === 'unlabeled') ?? props.dataset.images[0]
}

function openImage(item?: DatasetImage) {
  imageId.value = item?.id ?? ''
  hiddenAnnotationIds.value.clear()
  annotations.value = item ? JSON.parse(JSON.stringify(item.annotations)) as Annotation[] : []
  classes.value = props.dataset.classes.map(label => ({ ...label }))
  negative.value = item?.status === 'negative'
  activeClassId.value = annotations.value[0]?.class_id
    ?? (byClass.value.has(activeClassId.value) ? activeClassId.value : classes.value[0]?.id ?? '')
  baseline.value = snapshot(annotations.value, classes.value, status.value)
  unfinishedNotice.value = false
  selectedId.value = ''
  activeVertex.value = undefined
  activeKeypoint.value = ''
  activeVisibility.value = 2
  classForm.value = undefined
  draftPoints.value = 0
  tool.value = 'select'
  canvas.value?.cancelDraft()
}

watch([() => props.dataset.id, () => props.initialImageId], () => {
  split.value = 'all'
  openImage(firstImage())
}, { immediate: true })

watch(image, current => {
  if (!current && images.value.length && !dirty.value && !deleteTarget.value) openImage(images.value[0])
})

watch(draftPoints, count => { if (!count) unfinishedNotice.value = false })
watch(tool, value => { if (value !== 'select') activeVertex.value = undefined })

function ask(mode: typeof dialogMode.value) {
  if (!dialog.value || confirmResult) return false
  dialogMode.value = mode
  dialog.value.showModal()
  return new Promise<boolean>(resolve => { confirmResult = resolve })
}

function confirmLeave(): boolean | Promise<boolean> {
  if (props.busy || switchingView.value || confirmResult) return false
  return !dirty.value || ask('discard')
}
defineExpose({ confirmLeave })

function closeDialog(confirmed: boolean) {
  dialog.value?.close()
  confirmResult?.(confirmed)
  confirmResult = undefined
}

async function saveBeforeSwitch() {
  if (props.busy || switchingView.value || confirmResult) return false
  if (draftPoints.value) {
    unfinishedNotice.value = true
    return false
  }
  switchingView.value = true
  try {
    if (dirty.value && !(await save())) return false
    await nextTick()
    return true
  } finally {
    switchingView.value = false
  }
}

async function backToDatasets() {
  if (await saveBeforeSwitch()) emit('back')
}

async function selectImage(item: DatasetImage) {
  if (item.id !== imageId.value && await saveBeforeSwitch()) {
    openImage(images.value.find(candidate => candidate.id === item.id))
  }
}

async function removeImage(item: DatasetImage) {
  if (props.busy || deleteTarget.value) return
  deleteTarget.value = item
  try {
    if (!await ask('delete-image')) return
    const deletingCurrent = imageId.value === item.id
    const position = imageIndex.value
    if (await props.deleteImage(item.id) && deletingCurrent) {
      await nextTick()
      openImage(images.value[position] ?? images.value[position - 1])
    }
  } finally {
    deleteTarget.value = undefined
  }
}

async function setSplit(value: Filter) {
  if (split.value === value || !(await saveBeforeSwitch())) return
  split.value = value
  if (imageIndex.value < 0) openImage(images.value[0])
}

function step(offset: -1 | 1) {
  if (imageIndex.value < 0) return
  const next = images.value[imageIndex.value + offset]
  if (next) void selectImage(next)
}

async function save() {
  if (!image.value || props.busy || draftPoints.value) return false
  if (!dirty.value) return true
  const submitted = snapshot(annotations.value, classes.value, status.value)
  const saved = await props.saveAnnotations(imageId.value, JSON.parse(JSON.stringify(annotations.value)) as Annotation[],
    classes.value.map(label => ({ ...label })), status.value)
  if (saved) baseline.value = submitted
  return saved
}

function selectObject(id: string) {
  if (selectedId.value !== id) activeVertex.value = undefined
  selectedId.value = id
  if (!selected.value) {
    activeKeypoint.value = ''
    return
  }
  activeClassId.value = selected.value.class_id
  if (selected.value.type === 'pose' && !selected.value.keypoints.some(point => point.name === activeKeypoint.value)) {
    activeKeypoint.value = selected.value.keypoints[0]?.name ?? ''
  }
}

function selectFromList(id: string) {
  selectObject(id)
  if (polygonSelection.value && !draftPoints.value) tool.value = 'select'
}

function toggleAnnotationVisibility(id: string) {
  if (!hiddenAnnotationIds.value.delete(id)) {
    hiddenAnnotationIds.value.add(id)
    if (selectedId.value === id) activeVertex.value = undefined
  }
}

function update(item: Annotation) {
  if (props.busy) return
  annotations.value = annotations.value.map(previous => previous.id === item.id ? item : previous)
}

function add(item: Annotation) {
  if (props.busy) return
  negative.value = false
  annotations.value = [...annotations.value, item]
  selectObject(item.id)
  if (item.type === 'pose') {
    const first = item.keypoints[0]
    activeKeypoint.value = first?.name ?? ''
    tool.value = first ? 'keypoint' : 'select'
  } else {
    tool.value = 'select'
  }
}

function remove() {
  if (!selected.value || props.busy) return
  annotations.value = annotations.value.filter(item => item.id !== selectedId.value)
  selectObject('')
  tool.value = 'select'
}

function selectClass(id: string, assign = false) {
  if (props.busy || !image.value) return
  activeClassId.value = id
  if (props.dataset.task === 'classify') {
    if (annotations.value[0]?.class_id === id) return
    const label: Annotation = {
      id: annotations.value[0]?.id ?? createUuid(), class_id: id, source: 'manual', type: 'classify',
    }
    annotations.value = [label]
    selectObject(label.id)
  } else if (assign && selected.value) {
    update({ ...selected.value, class_id: id })
  }
}

function startClass(entry?: DatasetClass) {
  classForm.value = {
    entry, name: entry?.name ?? '', color: entry?.color.toLowerCase() ?? colors[classes.value.length % colors.length],
  }
  classError.value = ''
  void nextTick(() => classInput.value?.focus())
}

async function submitClass() {
  const draft = classForm.value
  const current = image.value
  if (!draft || props.busy || !current) return
  const { entry, color } = draft
  const name = draft.name.trim()
  if (!name) return
  if (classes.value.some(label => label.id !== entry?.id && label.name.toLowerCase() === name.toLowerCase())) {
    classError.value = '该类别已存在。'
    return
  }
  if (!entry) {
    const label = { id: createUuid(), name, color }
    classes.value = [...classes.value, label]
    selectClass(label.id)
  } else if (entry.name !== name || entry.color.toLowerCase() !== color) {
    const stored = props.dataset.classes.find(label => label.id === entry.id)
    let updated = { ...entry, name, color }
    if (stored) {
      try {
        updated = await props.editClass(entry, name, color)
      } catch (error) {
        classError.value = error instanceof Error ? error.message : '无法保存类别，请重试。'
        return
      }
      const savedClasses = props.dataset.classes.map(label => label.id === updated.id ? updated : label)
      baseline.value = snapshot(current.annotations, savedClasses, current.status)
    }
    classes.value = classes.value.map(label => label.id === updated.id ? updated : label)
  }
  classForm.value = undefined
}

async function markNegative() {
  if (!image.value || props.busy || props.dataset.task === 'classify') return
  if (negative.value) {
    negative.value = false
    return
  }
  if (annotations.value.length && !await ask('negative')) return
  annotations.value = []
  negative.value = true
  selectObject('')
  canvas.value?.cancelDraft()
  tool.value = 'select'
}

function chooseKeypoint(name: string, preferred?: 1 | 2) {
  if (!pose.value || props.busy) return
  focusKeypoint(pose.value.id, name, preferred)
  tool.value = 'keypoint'
}

function focusKeypoint(id: string, name: string, preferred?: 1 | 2) {
  if (id !== selectedId.value) return
  activeKeypoint.value = name
  activeVisibility.value = preferred ?? (pose.value?.keypoints.find(point => point.name === name)?.visible === 1 ? 1 : 2)
}

function setVisibility(name: string, value: 0 | 1 | 2) {
  if (!pose.value || props.busy) return
  const point = pose.value.keypoints.find(point => point.name === name)
  if (!point) return
  if (!point.visible && value) {
    chooseKeypoint(name, value)
    return
  }
  if (name === activeKeypoint.value && value) activeVisibility.value = value
  update({
    ...pose.value, keypoints: pose.value.keypoints.map(point => point.name === name
      ? { ...point, x: value ? point.x : 0, y: value ? point.y : 0, visible: value }
      : point),
  })
}

function shapeInfo(item: Annotation) {
  if (item.type === 'obb') return Math.round(item.obb.width) + '×' + Math.round(item.obb.height) + ' · ' + item.obb.angle.toFixed(1) + '°'
  if (item.type === 'polygon') return item.polygon.length + ' 个顶点'
  if (item.type === 'pose') return item.keypoints.filter(point => point.visible).length + ' / ' + item.keypoints.length + ' 关键点'
  if (item.type === 'bbox') return Math.round(item.bbox.width) + '×' + Math.round(item.bbox.height)
  return '图像类别'
}

function onKey(event: KeyboardEvent) {
  if (event.isComposing || dialog.value?.open || event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement
    || event.target instanceof HTMLSelectElement || (event.target instanceof HTMLElement && event.target.isContentEditable)) return
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    void save()
    return
  }
  if (event.ctrlKey || event.metaKey || event.altKey || props.busy) return
  switch (event.key.toLowerCase()) {
    case 'd':
    case 'arrowleft': event.preventDefault(); if (!event.repeat) void step(-1); break
    case 'f':
    case 'arrowright': event.preventDefault(); if (!event.repeat) void step(1); break
    case 'delete':
      if (event.repeat) break
      if (tool.value === 'select' && polygonSelection.value && activeVertex.value !== undefined) {
        event.preventDefault()
        canvas.value?.removeVertex()
      } else remove()
      break
    case 'escape': canvas.value?.cancelDraft(); selectObject(''); tool.value = 'select'; break
    case 'enter': if (draftPoints.value) { event.preventDefault(); canvas.value?.finishPolygon() }; break
    case 'v': tool.value = 'select'; break
    case 'o': if (canDraw.value) tool.value = 'draw'; break
    case 'h': tool.value = 'pan'; break
    default: {
      const index = Number(event.key) - 1
      const label = classes.value[index]
      if (index >= 0 && index < 9 && label) selectClass(label.id, tool.value === 'select')
    }
  }
}

function onUnload(event: BeforeUnloadEvent) {
  if (dirty.value || props.busy) event.preventDefault()
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  window.addEventListener('beforeunload', onUnload)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('beforeunload', onUnload)
  confirmResult?.(false)
})
</script>

<template>
  <main class="annotation">
    <header class="annotation-bar">
      <button class="button" :disabled="busy || switchingView" @click="backToDatasets">← 返回数据集</button>
      <div class="image-context">
        <strong>{{ dataset.name }}</strong>
        <span v-if="image" class="file-tag" :title="image.name">{{ image.name }}</span>
        <span v-if="image" class="technical">{{ image.width }} × {{ image.height }} px</span>
      </div>
      <span class="technical image-navigation">{{ imageIndex + 1 }} / {{ images.length }} 张</span>
      <span v-if="image" class="save-status" :class="[status, { dirty }]" role="status">
        {{ busy ? (deleteTarget ? '删除中…' : '保存中…') : dirty ? '有未保存修改' : (image.version ? '已保存 · ' : '') + statusText[status] }}
      </span>
      <button class="button primary" :disabled="!dirty || busy || !image || draftPoints > 0" @click="save">保存标注 <kbd>Ctrl+S</kbd></button>
    </header>
    <p v-if="error" class="save-error" role="alert">{{ error }}</p>

    <div class="annotation-body">
      <aside class="image-rail" aria-label="数据集图片">
        <div class="image-filters">
          <button v-for="filter in filters" :key="filter.value" type="button" :aria-pressed="split === filter.value" :disabled="busy || switchingView"
            :class="{ active: split === filter.value }" @click="setSplit(filter.value)">{{ filter.label }}</button>
        </div>
        <div class="rail-summary"><span>当前子集</span><strong class="technical">共 {{ images.length }} 张</strong></div>
        <fieldset class="image-list" :disabled="busy || switchingView" aria-label="图片列表">
          <div v-for="item in images" :key="item.id" v-memo="[item, item.id === imageId, item.id === imageId ? status : item.status]"
            class="image-entry" :class="{ active: item.id === imageId }">
            <button type="button" class="image-item" :aria-current="item.id === imageId ? 'true' : undefined"
              @click="selectImage(item)">
              <img v-if="item.src" :src="item.src" alt="" loading="lazy">
              <span v-else class="image-placeholder" aria-hidden="true">▧</span>
              <span class="image-meta">
                <span class="image-name technical" :title="item.name">{{ item.name }}</span>
                <span class="image-tags">
                  <span class="split-tag">{{ item.split ?? '未分集' }}</span>
                  <span :class="item.id === imageId ? status : item.status">{{ statusText[item.id === imageId ? status : item.status] }}</span>
                </span>
              </span>
            </button>
            <button class="button image-delete" type="button" title="删除图片" :aria-label="'删除图片 ' + item.name"
              @click="removeImage(item)">
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
                <path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>
              </svg>
            </button>
          </div>
          <p v-if="!images.length" class="empty">当前分集暂无图片。</p>
        </fieldset>
      </aside>

      <section class="workspace" :class="{ gridded: grid }" :aria-label="taskLabels[dataset.task] + '画布'">
        <div class="canvas-tools" role="toolbar" aria-label="标注工具">
          <button class="button" type="button" aria-label="上一张" aria-keyshortcuts="D" title="上一张（D）"
            :disabled="busy || switchingView || imageIndex <= 0" @click="step(-1)">上一张 <kbd>D</kbd></button>
          <button class="button" type="button" aria-label="下一张" aria-keyshortcuts="F" title="下一张（F）"
            :disabled="busy || switchingView || imageIndex < 0 || imageIndex >= images.length - 1" @click="step(1)">下一张 <kbd>F</kbd></button>
          <span class="tool-divider"></span>
          <template v-if="dataset.task !== 'classify'">
            <button class="button" :class="{ chosen: tool === 'select' }" :aria-pressed="tool === 'select'" @click="tool = 'select'">选择 <kbd>V</kbd></button>
            <button class="button" :class="{ chosen: tool === 'draw' }" :aria-pressed="tool === 'draw'" :disabled="!canDraw" @click="tool = 'draw'">{{ drawLabel }} <kbd>O</kbd></button>
            <button v-if="dataset.task === 'pose'" class="button" :class="{ chosen: tool === 'keypoint' }" :aria-pressed="tool === 'keypoint'"
              :disabled="selectedHidden || !pose || !activeKeypoint || busy" @click="chooseKeypoint(activeKeypoint)">放置关键点</button>
          </template>
          <button class="button" :class="{ chosen: tool === 'pan' }" :aria-pressed="tool === 'pan'" @click="tool = 'pan'">抓手 <kbd>H</kbd></button>
          <span class="tool-divider"></span>
          <button class="button arrow" aria-label="缩小" @click="canvas?.zoomBy(1 / 1.2)">−</button>
          <span class="technical zoom-value">{{ Math.round(zoom * 100) }}%</span>
          <button class="button arrow" aria-label="放大" @click="canvas?.zoomBy(1.2)">+</button>
          <button class="button" @click="canvas?.fit()">适应窗口</button>
          <button class="button" :class="{ chosen: grid }" :aria-pressed="grid" @click="grid = !grid">网格</button>
          <template v-if="dataset.task === 'obb'">
            <span class="tool-divider"></span>
            <button class="button technical" :disabled="selectedHidden || selected?.type !== 'obb' || busy" title="逆时针微调" @click="canvas?.nudgeAngle(-0.5)">−0.5°</button>
            <button class="button technical" :disabled="selectedHidden || selected?.type !== 'obb' || busy" title="顺时针微调" @click="canvas?.nudgeAngle(0.5)">+0.5°</button>
          </template>
        </div>
        <div v-if="tool === 'draw' && dataset.task === 'segment'" class="canvas-hint" aria-live="polite">
          <span v-if="unfinishedNotice" class="class-error">请先完成或取消当前多边形。</span>
          <span>依次点击顶点 · 已放置 {{ draftPoints }} 点</span>
          <button class="button primary" :disabled="draftPoints < 3 || busy" @click="canvas?.finishPolygon()">完成多边形</button>
          <button class="button" :disabled="!draftPoints" @click="canvas?.cancelDraft()">取消绘制</button>
        </div>
        <div v-else-if="tool === 'select' && polygonSelection" class="canvas-hint" aria-live="polite">
          <span>顶点编辑 · 拖动方点调整，双击边线加点</span>
          <span v-if="activeVertex !== undefined">已选顶点 {{ activeVertex + 1 }}</span>
          <button class="button" type="button" :disabled="busy || activeVertex === undefined || polygonSelection.polygon.length <= 3"
            title="至少保留 3 个顶点" @click="canvas?.removeVertex()">删除顶点 <kbd>Del</kbd></button>
        </div>
        <div v-else-if="tool === 'keypoint' && activeKeypoint" class="canvas-hint">在图片上点击放置「{{ activeKeypoint }}」</div>
        <div class="canvas-area">
          <AnnotationCanvas ref="canvas" :image="image" :annotations="annotations" :hidden-annotation-ids="hiddenAnnotationIds" :classes="classes"
            :task="dataset.task" :tool="tool" :selected-id="selectedId" :active-vertex="activeVertex" :active-class-id="activeClassId"
            :active-keypoint="activeKeypoint" :active-visibility="activeVisibility" :keypoint-names="dataset.keypointNames" :busy="busy"
            @select="selectObject" @create="add" @update="update" @vertex="activeVertex = $event" @keypoint="focusKeypoint"
            @zoom="zoom = $event" @draft="draftPoints = $event" />
        </div>
        <footer class="canvas-status technical">
          <span>原图像素坐标</span><span>{{ taskLabels[dataset.task] }}</span>
          <span v-if="dataset.task === 'classify'">点击类别为当前图片设置标签</span>
        </footer>
      </section>

      <aside class="object-rail" aria-label="类别与标注对象">
        <section class="classes-panel">
          <div class="rail-heading">
            <h2>类别 <small>({{ classes.length }})</small></h2>
            <button class="button" :disabled="busy || !image" @click="startClass()">＋ 新增类别</button>
          </div>
          <form v-if="classForm" class="add-class" @submit.prevent="submitClass">
            <label for="annotation-class-name">类别名称</label>
            <input id="annotation-class-name" ref="classInput" v-model="classForm.name" maxlength="120"
              :disabled="busy" required placeholder="输入类别名称" @input="classError = ''">
            <label class="class-color" for="annotation-class-color">
              显示颜色
              <input id="annotation-class-color" v-model="classForm.color" type="color" :disabled="busy">
              <span class="technical">{{ classForm.color }}</span>
            </label>
            <div>
              <button class="button primary" type="submit" :disabled="!classForm.name.trim() || busy">{{ classForm.entry ? '保存修改' : '添加' }}</button>
              <button class="button" type="button" :disabled="busy" @click="classForm = undefined">取消</button>
            </div>
            <span v-if="classError" class="class-error" role="alert">{{ classError }}</span>
          </form>
          <div class="class-list">
            <div v-for="(entry, index) in classes" :key="entry.id" class="class-entry">
              <button class="class-row" :class="{ active: entry.id === activeClassId }" :aria-pressed="entry.id === activeClassId"
                :disabled="busy || !image" @click="selectClass(entry.id, tool === 'select')">
                <span class="technical">{{ entry.index ?? index }}</span>
                <i :style="{ backgroundColor: entry.color }"></i><strong>{{ entry.name }}</strong>
                <kbd v-if="index < 9">{{ index + 1 }}</kbd>
                <span class="technical class-total">{{ annotations.filter(item => item.class_id === entry.id).length }} 个</span>
              </button>
              <button class="button" type="button" :aria-label="'编辑类别 ' + entry.name"
                :disabled="busy || !image" @click="startClass(entry)">编辑</button>
            </div>
            <p v-if="!classes.length && !classForm" class="empty">请新增类别后开始标注。</p>
          </div>
        </section>
        <section class="objects-panel">
          <div class="rail-heading">
            <h2>当前标注 <small>({{ annotations.length }})</small></h2>
            <button v-if="dataset.task !== 'classify'" class="button" :aria-pressed="negative"
              :disabled="busy || !image" @click="markNegative">{{ negative ? '取消负样本' : '标为负样本' }}</button>
          </div>
          <div class="object-list">
            <div v-for="(item, index) in annotations" :key="item.id" class="object-entry" :class="{ active: item.id === selectedId }">
              <button type="button" class="object-row" :aria-pressed="item.id === selectedId" @click="selectFromList(item.id)">
                <i :style="{ backgroundColor: byClass.get(item.class_id)?.color }"></i>
                <span class="technical">#{{ String(index + 1).padStart(2, '0') }}</span>
                <span class="object-name">{{ byClass.get(item.class_id)?.name ?? '未知类别' }}</span>
                <small class="technical">{{ shapeInfo(item) }}</small>
              </button>
              <button v-if="item.type !== 'classify'" type="button" class="button object-visibility"
                :class="{ hidden: hiddenAnnotationIds.has(item.id) }"
                :title="hiddenAnnotationIds.has(item.id) ? '显示标注' : '隐藏标注'"
                :aria-label="`${hiddenAnnotationIds.has(item.id) ? '显示标注' : '隐藏标注'} #${index + 1}`"
                @click="toggleAnnotationVisibility(item.id)">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7"
                  stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6Z"/>
                  <circle cx="12" cy="12" r="2.5"/>
                  <path v-if="hiddenAnnotationIds.has(item.id)" d="m3 3 18 18"/>
                </svg>
              </button>
            </div>
            <p v-if="!annotations.length" class="empty">{{ negative ? '此图已标为负样本。' : '当前图片暂无标注。' }}</p>
          </div>
          <div v-if="pose" class="keypoints" aria-label="姿态关键点">
            <h3>关键点</h3>
            <div v-for="(point, index) in pose.keypoints" :key="point.name" class="point-row" :class="{ active: point.name === activeKeypoint }">
              <button class="button" :disabled="busy" @click="chooseKeypoint(point.name)">{{ index + 1 }}. {{ point.name }}</button>
              <select :value="point.visible" :disabled="busy" :aria-label="point.name + '可见性'"
                @change="setVisibility(point.name, Number(($event.target as HTMLSelectElement).value) as 0 | 1 | 2)">
                <option v-for="option in visibility" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </div>
          </div>
          <footer v-if="selected" class="object-actions">
            <label><span>所选标注类别</span>
              <select :value="selected.class_id" :disabled="busy" @change="selectClass(($event.target as HTMLSelectElement).value, true)">
                <option v-for="entry in classes" :key="entry.id" :value="entry.id">{{ entry.name }}</option>
              </select>
            </label>
            <button class="button danger" :disabled="busy" @click="remove">删除</button>
          </footer>
        </section>
      </aside>
    </div>

    <dialog ref="dialog" class="discard-dialog" aria-labelledby="annotation-dialog-heading" @cancel.prevent="closeDialog(false)">
      <h2 id="annotation-dialog-heading">{{ dialogMode === 'delete-image' ? '删除图片？' : dialogMode === 'negative' ? '标为负样本？' : '未保存修改确认' }}</h2>
      <template v-if="dialogMode === 'delete-image'">
        <p class="delete-image-name"><strong>{{ deleteTarget?.name }}</strong></p>
        <p>这会永久删除该图片及其标注。此操作无法撤销。</p>
        <p v-if="deleteTarget?.id === imageId && dirty">这张图片上未保存的修改也会丢失。</p>
      </template>
      <p v-else>{{ dialogMode === 'negative' ? '当前图片中的标注将从草稿移除。保存后，图片会记录为负样本。' : '当前图片有未保存的修改。离开后，这些修改将丢失。' }}</p>
      <div class="discard-actions">
        <button class="button" autofocus @click="closeDialog(false)">{{ dialogMode === 'discard' ? '继续编辑' : '取消' }}</button>
        <button class="button danger" @click="closeDialog(true)">{{ dialogMode === 'delete-image' ? '确认删除' : dialogMode === 'negative' ? '移除标注并标记' : '放弃修改并离开' }}</button>
      </div>
    </dialog>
  </main>
</template>

<style scoped>

.annotation { display:flex; flex-direction:column; height:100dvh; min-height:550px; overflow:hidden; color:var(--text,#111c2b); background:var(--surface,#fff); font-size:13px; }
.annotation-bar { min-height:54px; display:flex; align-items:center; flex-wrap:wrap; gap:8px 12px; padding:8px 16px; border-bottom:1px solid var(--line,#c3c6ce); }
.annotation button { cursor:pointer; }
.annotation button:disabled { cursor:not-allowed; }
.annotation .button { white-space:nowrap; }
.annotation .button.arrow { min-width:28px; padding-inline:7px; }
.annotation button:focus-visible, .annotation select:focus-visible, .annotation input:focus-visible { outline:2px solid var(--primary,#4f6885); outline-offset:2px; }
.image-context { min-width:0; flex:1 1 250px; display:flex; align-items:center; gap:10px; }
.image-context strong { white-space:nowrap; }
.technical, kbd, .file-tag { font-family:ui-monospace, 'Cascadia Mono', Consolas, monospace; font-variant-numeric:tabular-nums; }
.file-tag { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; padding:2px 6px; background:var(--selected,#e6eeff); border:1px solid var(--line,#c3c6ce); }
.image-navigation { display:flex; align-items:center; gap:8px; white-space:nowrap; }
.save-status { padding:3px 7px; white-space:nowrap; color:#16643a; background:#edf8f0; border:1px solid #c7e5d0; }
.save-status.unlabeled { color:var(--muted,#5c6775); background:var(--soft,#f5f7fa); border-color:var(--line,#c3c6ce); }
.save-status.negative { color:#8b4c13; background:#fff8e7; border-color:#f0d799; }
.save-status.dirty { color:#8b4c13; background:#fff8e7; border-color:#f0d799; }
.save-error { margin:0; padding:7px 16px; color:#a32a22; background:#fff0ef; border-bottom:1px solid #efccc8; }
.annotation-body { flex:1; min-height:0; display:grid; grid-template-columns:minmax(155px, 17%) minmax(260px, 1fr) minmax(220px, 21%); }
.image-rail, .object-rail { min-width:0; min-height:0; display:flex; flex-direction:column; background:var(--surface,#fff); }
.image-rail { border-right:1px solid var(--line,#c3c6ce); }
.object-rail { border-left:1px solid var(--line,#c3c6ce); }
.image-filters { display:flex; margin:8px 8px 0; padding:2px; gap:2px; background:var(--soft,#f5f7fa); }
.image-filters button { flex:1; min-width:0; padding:4px 2px; background:transparent; color:var(--text,#111c2b); border:1px solid transparent; font-family:ui-monospace, monospace; font-size:12px; }
.image-filters button.active { background:var(--surface,#fff); border-color:var(--line,#c3c6ce); }
.rail-summary { display:flex; justify-content:space-between; gap:6px; padding:8px 10px; border-bottom:1px solid var(--line,#c3c6ce); color:var(--muted,#5c6775); font-size:11px; }
.image-list, .object-list, .class-list { min-height:0; overflow:auto; }
.image-list { min-width:0; margin:0; padding:0; border:0; }
.image-entry { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; padding-right:6px; border-bottom:1px solid var(--line,#c3c6ce); }
.image-item { display:flex; min-width:0; align-items:center; gap:8px; padding:8px 4px 8px 8px; border:0; background:transparent; color:inherit; text-align:left; }
.image-entry:hover, .image-entry.active, .class-row.active, .object-entry.active { background:var(--selected,#e6eeff); }
.image-entry.active { box-shadow:inset 3px 0 var(--primary,#4f6885); }
.image-delete { display:grid; place-items:center; width:26px; min-height:26px; padding:3px; color:var(--muted,#5c6775); background:transparent; border-color:transparent; }
.image-delete:hover:not(:disabled) { color:#a32a22; border-color:#efccc8; background:#fff0ef; }
.image-item img, .image-placeholder { display:grid; place-items:center; flex:0 0 58px; width:58px; height:43px; object-fit:cover; background:var(--soft,#f5f7fa); border:1px solid var(--line,#c3c6ce); }
.image-meta { flex:1; display:grid; gap:5px; min-width:0; }
.image-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px; }
.image-tags { display:flex; justify-content:space-between; align-items:center; gap:3px; font-size:10px; }
.image-tags span { padding:1px 3px; white-space:nowrap; background:var(--soft,#f5f7fa); }
.image-tags .split-tag { font-family:ui-monospace, monospace; }
.image-tags .annotated { background:#edf8f0; color:#16643a; }
.workspace { display:flex; flex-direction:column; min-height:0; min-width:0; position:relative; overflow:hidden; background:#f1f3f5; }
.workspace.gridded { background-image:linear-gradient(#74849c16 1px, transparent 1px),linear-gradient(90deg,#74849c16 1px,transparent 1px); background-size:24px 24px; }
.canvas-tools { z-index:1; position:absolute; left:50%; top:10px; transform:translateX(-50%); display:flex; justify-content:center; align-items:center; flex-wrap:wrap; gap:4px; width:max-content; max-width:calc(100% - 20px); padding:5px; background:var(--surface,#fff); border:1px solid var(--line,#c3c6ce); box-shadow:0 2px 5px #16223510; }
.canvas-tools .button { padding:4px 6px; font-size:12px; }
.canvas-tools .chosen { background:var(--selected,#e6eeff); color:var(--primary,#4f6885); }
.tool-divider { height:16px; border-left:1px solid var(--line,#c3c6ce); margin-inline:2px; }
.zoom-value { text-align:center; min-width:35px; font-size:11px; }
.canvas-area { position:relative; flex:1; min-height:0; margin:75px 20px 14px; }
.canvas-status { min-height:28px; display:flex; justify-content:space-between; gap:8px; align-items:center; padding:3px 10px; border-top:1px solid var(--line,#c3c6ce); background:var(--surface,#fff); color:var(--muted,#5c6775); font-size:11px; }
.classes-panel, .objects-panel { min-height:0; display:flex; flex-direction:column; }
.classes-panel { flex:0 0 42%; }
.objects-panel { flex:1; }
.rail-heading { min-height:40px; flex:none; display:flex; justify-content:space-between; align-items:center; gap:4px; padding:6px 10px; border-block-end:1px solid var(--line,#c3c6ce); background:var(--soft,#f5f7fa); }
.objects-panel .rail-heading { border-block-start:1px solid var(--line,#c3c6ce); }
.rail-heading h2 { margin:0; font-size:15px; }
.rail-heading small { font-weight:400; color:var(--muted,#5c6775); }
.rail-heading .button { padding:3px 6px; font-size:11px; }
.class-list { padding:6px; }
.class-entry { display:grid; grid-template-columns:minmax(0, 1fr) auto; align-items:center; gap:4px; }
.class-row { min-width:0; width:100%; display:flex; align-items:center; gap:7px; padding:7px; text-align:left; color:inherit; background:transparent; border:1px solid transparent; }
.class-entry > .button { min-height:24px; padding:3px 6px; font-size:11px; }
.class-row.active { border-color:var(--line,#c3c6ce); }
.class-row i, .object-row i { flex:0 0 9px; width:9px; height:9px; border-radius:2px; }
.class-row strong { overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.class-row kbd { background:var(--soft,#f5f7fa); padding:1px 4px; }
.class-total { margin-left:auto; flex:none; font-size:11px; }
.add-class { display:grid; gap:5px; margin:8px; font-size:12px; }
.add-class > div { display:flex; gap:4px; }
.add-class input { min-width:0; }
.class-color { display:flex; align-items:center; gap:6px; }
.class-color input { width:36px; height:24px; padding:1px 2px; }
.annotation input, .annotation select { border:1px solid var(--line,#c3c6ce); padding:4px 5px; background:var(--surface,#fff); color:inherit; font:inherit; }
.class-error { color:#a32a22; }
.object-list { flex:1; }
.object-entry { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; border-bottom:1px solid var(--line,#c3c6ce); }
.object-row { min-width:0; width:100%; border:0; background:transparent; color:inherit; display:flex; gap:5px; align-items:center; text-align:left; padding:8px; }
.object-visibility { display:grid; place-items:center; width:26px; min-height:26px; padding:3px; margin-right:6px; color:var(--primary,#4f6885); background:transparent; border-color:transparent; }
.object-visibility.hidden { color:var(--muted,#5c6775); }
.object-row i { flex-basis:7px; width:7px; height:7px; border-radius:50%; }
.object-name { min-width:0; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.object-row small { flex:none; color:var(--muted,#5c6775); font-size:10px; }
.object-actions { display:flex; flex-wrap:wrap; align-items:center; gap:5px; padding:6px; border-top:1px solid var(--line,#c3c6ce); background:var(--soft,#f5f7fa); }
.object-actions label { flex:1; display:flex; align-items:center; min-width:0; gap:4px; }
.object-actions label span { white-space:nowrap; font-size:11px; }
.object-actions select { width:100%; min-width:0; }
.object-actions .button { padding:3px 5px; font-size:11px; }
.empty { padding:8px 10px; color:var(--muted,#5c6775); font-size:12px; }
.discard-dialog { width:min(450px, calc(100% - 24px)); box-sizing:border-box; padding:22px; color:var(--text,#111c2b); border:1px solid var(--line,#c3c6ce); border-radius:8px; background:var(--surface,#fff); }
.discard-dialog::backdrop { background:#26314166; }
.discard-dialog h2 { margin:0 0 8px; font-size:18px; }
.discard-dialog p { color:var(--muted,#5c6775); }
.delete-image-name { overflow-wrap:anywhere; }
.discard-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:20px; }
@media (max-width: 960px) {
  .annotation-body { grid-template-columns:145px minmax(220px, 1fr) 195px; }
  .annotation-bar { gap:5px; padding-inline:8px; }
  .image-context > .technical { display:none; }
  .canvas-area { margin-inline:8px; }
  .object-row small { display:none; }
}



.canvas-hint { position:absolute; z-index:1; top:52px; left:50%; transform:translateX(-50%); display:flex; align-items:center; gap:5px; padding:4px 6px; white-space:nowrap; color:var(--muted,#5c6775); background:var(--surface,#fff); border:1px solid var(--line,#c3c6ce); font-size:11px; }
.canvas-hint .button { font-size:11px; padding:2px 5px; }
.canvas-area { margin-top:88px; }
.image-tags .negative { background:#fff8e7; color:#8b4c13; }
.image-filters button { flex:1 1 auto; font-size:11px; }
.keypoints { border-top:1px solid var(--line,#c3c6ce); padding:6px 8px; max-height:48%; overflow:auto; }
.keypoints h3 { margin:0 0 4px; font-size:12px; }
.point-row { display:flex; justify-content:space-between; align-items:center; gap:5px; padding:2px 4px; }
.point-row .button { min-width:0; overflow:hidden; text-overflow:ellipsis; font-size:11px; padding:3px 5px; }
.point-row.active { background:var(--selected,#e6eeff); }
.point-row select { flex:none; font-size:11px; }
</style>
