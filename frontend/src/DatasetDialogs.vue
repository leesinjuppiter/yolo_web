<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { datasetCounts, taskLabels } from './domain'
import type { Dataset, DialogKind, Split, TaskType } from './domain'

const props = defineProps<{ kind: Exclude<DialogKind, 'import' | 'export'> | null; dataset?: Dataset; busy?: boolean; error?: string }>()
const emit = defineEmits<{
  close: []
  create: [name: string, task: TaskType, keypoints: string[]]
  add: [files: File[], split: Split | null]
  splits: [splits: Record<string, Split | null>]
  delete: []
  notice: [message: string]
}>()

const dialog = ref<HTMLDialogElement>()
const name = ref('')
const task = ref<TaskType>('obb')
const split = ref<Split | null>(null)
const splits = ref<Record<string, Split | null>>({})
const keypoints = ref('')
const keypointNames = computed(() => keypoints.value.split(/[,，、\n]/).map(point => point.trim()).filter(Boolean))
const files = ref<{ file: File; preview: string }[]>([])
const fileError = ref('')
const confidence = ref(0.25)
const includeAnnotated = ref(false)

const tasks: { id: TaskType; description: string }[] = [
  { id: 'detect', description: '为目标绘制水平矩形框' },
  { id: 'segment', description: '使用多边形描出目标轮廓' },
  { id: 'obb', description: '为倾斜目标绘制可旋转的框' },
  { id: 'classify', description: '为整张图片选择一个类别' },
  { id: 'pose', description: '绘制目标框并标注关键点' },
]

const counts = computed(() => props.dataset ? datasetCounts(props.dataset) : { images: 0, annotated: 0, classes: 0 })
const displayCount = computed(() => counts.value.images.toLocaleString('zh-CN'))

const content = computed(() => {
  const target = props.dataset?.name ?? ''
  switch (props.kind) {
    case 'create':
      return { title: '新建数据集', description: '填写名称并选择任务类型，创建后即可添加图片。', action: '创建数据集' }
    case 'add':
      return {
        title: `向「${target}」添加图片`,
        description: '选择图片和分集，保存到当前数据集。',
        action: files.value.length ? `添加 ${files.value.length} 张图片` : '添加图片',
      }
    case 'delete':
      return { title: `删除数据集「${target}」？`, description: '', action: '确认删除' }
    case 'splits':
      return { title: `调整分集「${target}」`, description: '设置各图片所属分集。导出时将使用已保存的结果。', action: '保存分集' }
    case 'auto':
      return {
        title: `自动标注「${target}」`,
        description: '配置模型推理参数，生成供人工检查的候选标注。',
        action: '查看自动标注演示',
      }
    default:
      return { title: '', description: '', action: '' }
  }
})

const pendingLabels = {
  create: '创建中…', add: '添加中…', delete: '删除中…', auto: '准备任务…', splits: '保存中…',
}

const actionDisabled = computed(() => {
  if (props.busy) return true
  if (props.kind === 'create') return !name.value.trim() || (task.value === 'pose' &&
    (!keypointNames.value.length || new Set(keypointNames.value).size !== keypointNames.value.length))
  if (props.kind === 'add') return !files.value.length
  return false
})

function clearImages() {
  for (const { preview } of files.value) URL.revokeObjectURL(preview)
  files.value = []
}

function removeImage(index: number) {
  const [image] = files.value.splice(index, 1)
  if (image) URL.revokeObjectURL(image.preview)
}

onBeforeUnmount(clearImages)

watch([() => props.kind, dialog], ([kind]) => {
  clearImages()
  if (!kind) {
    dialog.value?.close()
    return
  }
  name.value = ''
  task.value = 'obb'
  split.value = null
  splits.value = Object.fromEntries(props.dataset?.images.map(image => [image.id, image.split]) ?? [])
  keypoints.value = ''
  fileError.value = ''
  confidence.value = 0.25
  includeAnnotated.value = false
  if (dialog.value && !dialog.value.open) dialog.value.showModal()
}, { flush: 'post', immediate: true })

function close() {
  if (!props.busy) emit('close')
}

function selectFiles(newFiles: FileList | null) {
  if (!newFiles || props.busy) return
  const selected = Array.from(newFiles)
  const accepted = selected.filter((file) => /\.(jpe?g|png|webp|bmp)$/i.test(file.name) && file.size > 0)
  fileError.value = selected.length === accepted.length
    ? '' : `已跳过 ${selected.length - accepted.length} 个空文件或不支持的文件。`
  const all = [...files.value]
  for (const file of accepted) {
    if (!all.some(({ file: item }) => item.name === file.name && item.size === file.size &&
      item.lastModified === file.lastModified)) all.push({ file, preview: URL.createObjectURL(file) })
  }
  files.value = all
}

function pickImages(event: Event) {
  const input = event.target as HTMLInputElement
  selectFiles(input.files)
  input.value = ''
}

function submit() {
  if (actionDisabled.value) return
  switch (props.kind) {
    case 'create':
      emit('create', name.value.trim(), task.value, task.value === 'pose' ? keypointNames.value : [])
      break
    case 'add':
      if (props.dataset) emit('add', files.value.map((item) => item.file), split.value)
      break
    case 'delete':
      if (props.dataset) emit('delete')
      break
    case 'splits':
      emit('splits', { ...splits.value })
      break
    case 'auto':
      emit('notice', '自动标注参数已确认。接入模型服务后可提交推理任务。')
      emit('close')
      break
  }
}
</script>

<template>
  <dialog
    ref="dialog"
    class="dataset-dialog"
    :class="{ 'dataset-dialog--compact': kind === 'delete' }"
    aria-labelledby="dataset-dialog-title"
    :aria-busy="busy"
    @cancel.prevent="close"
  >
    <form v-if="kind" @submit.prevent="submit">
      <header class="dialog-header">
        <h2 id="dataset-dialog-title">{{ content.title }}</h2>
        <p v-if="content.description">{{ content.description }}</p>
        <button class="close-dialog" type="button" aria-label="关闭弹窗" :disabled="busy" @click="close">×</button>
      </header>

      <fieldset class="dialog-body" :disabled="busy">
        <template v-if="kind === 'create'">
          <label class="field-label" for="dataset-name">数据集名称 <span class="required-mark">*</span></label>
          <input
            id="dataset-name" v-model="name" type="text" maxlength="80"
            autocomplete="off" placeholder="例如：煤矸石皮带 · 夜班" required autofocus
          >
          <div class="field-label task-label" id="dataset-task-label">任务类型 <span class="required-mark">*</span></div>
          <div class="option-grid" role="radiogroup" aria-labelledby="dataset-task-label">
            <label v-for="item in tasks" :key="item.id" class="option" :class="{ selected: task === item.id }">
              <input v-model="task" type="radio" name="dataset-task" :value="item.id">
              <span><strong>{{ taskLabels[item.id] }}</strong><small>{{ item.description }}</small></span>
            </label>
          </div>
          <template v-if="task === 'pose'">
            <label class="field-label task-label" for="pose-keypoints">关键点名称 <span class="required-mark">*</span></label>
            <input id="pose-keypoints" v-model="keypoints" type="text" placeholder="例如：中心点，左端，右端" required>
            <p v-if="new Set(keypointNames).size !== keypointNames.length" class="dialog-error">关键点名称不能重复。</p>
          </template>
        </template>

        <template v-else-if="kind === 'add'">
          <label class="field-label" for="dataset-split">导入到 split</label>
          <select id="dataset-split" v-model="split">
            <option :value="null">待分配</option>
            <option value="train">train · 训练集</option>
            <option value="val">val · 验证集</option>
            <option value="test">test · 测试集</option>
          </select>
          <label class="drop-area" @dragover.prevent @drop.prevent="selectFiles($event.dataTransfer?.files ?? null)">
            <input class="file-input" type="file" accept=".jpg,.jpeg,.png,.webp,.bmp" multiple @change="pickImages">
            <span class="upload-icon" aria-hidden="true">↑</span>
            <strong>拖放或选择图片</strong>
            <small>支持 JPG、PNG、WebP、BMP，可多选</small>
          </label>
          <ul v-if="files.length" class="file-list" aria-label="已选择图片">
            <li v-for="(item, index) in files" :key="item.preview">
              <img :src="item.preview" alt="" loading="lazy">
              <span :title="item.file.name">{{ item.file.name }}</span>
              <button type="button" :aria-label="`移除 ${item.file.name}`" @click="removeImage(index)">移除</button>
            </li>
          </ul>
        </template>

        <div v-else-if="kind === 'splits'" class="split-list">
          <label v-for="image in dataset?.images" :key="image.id">
            <span :title="image.name">{{ image.name }}</span>
            <select v-model="splits[image.id]" :aria-label="`${image.name} 的分集`">
              <option :value="null">待分配</option>
              <option value="train">train · 训练集</option>
              <option value="val">val · 验证集</option>
              <option value="test">test · 测试集</option>
            </select>
          </label>
        </div>

        <p v-else-if="kind === 'delete'" class="delete-description">
          这会永久删除该数据集及其 {{ displayCount }} 张图片、类别和标注。<strong>此操作无法撤销。</strong>
        </p>

        <template v-else-if="kind === 'auto'">
          <p class="demo-note">演示模式 · 模型服务接入后可提交任务</p>
          <label class="field-label" for="auto-confidence">置信度阈值 <output>{{ confidence.toFixed(2) }}</output></label>
          <input id="auto-confidence" v-model.number="confidence" type="range" min="0.05" max="0.95" step="0.05">
          <label class="check-row"><input v-model="includeAnnotated" type="checkbox"> 包含已有标注的图片</label>
        </template>

        <p v-if="error || fileError" class="dialog-error" role="alert">{{ error || fileError }}</p>
      </fieldset>

      <footer class="dialog-footer">
        <span v-if="kind === 'add'" class="footer-note">选中的图片将保存到本地标注服务。</span>
        <button type="button" class="button" :disabled="busy" :autofocus="kind === 'delete'" @click="close">取消</button>
        <button
          type="submit" class="button" :class="kind === 'delete' ? 'danger' : 'primary'"
          :disabled="actionDisabled"
        >{{ busy ? pendingLabels[kind] : content.action }}</button>
      </footer>
    </form>
  </dialog>
</template>

<style scoped>
.dataset-dialog {
  width: min(600px, calc(100vw - 36px));
  max-height: calc(100dvh - 36px);
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 16px 44px #21355124;
}
.dataset-dialog--compact { width: min(510px, calc(100vw - 36px)); }
.dataset-dialog::backdrop { background: #202e4580; backdrop-filter: blur(2px); }
.dialog-header { position: relative; padding: 23px 52px 0 24px; }
.dialog-header h2 { margin: 0; font-size: 21px; line-height: 1.35; overflow-wrap: anywhere; }
.dialog-header p { margin: 7px 0 0; color: var(--muted); font-size: 13px; }
.close-dialog {
  position: absolute;
  top: 17px;
  right: 17px;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 6px;
  background: var(--soft);
  color: var(--muted);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}
.dialog-body { min-width: 0; margin: 0; padding: 20px 24px; border: 0; font-size: 13px; }
.field-label { display: block; margin-bottom: 7px; font-weight: 600; }
.task-label { margin-top: 16px; }
.required-mark { color: #a42d3c; }
.dialog-body input[type="text"], .dialog-body select {
  box-sizing: border-box;
  width: 100%;
  min-height: 38px;
  padding: 8px 11px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
}
.option-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.option {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.option.selected { border-color: var(--primary); background: var(--selected); }
.option input { margin: 2px 0 0; accent-color: var(--primary); }
.option small, .drop-area small { display: block; margin-top: 4px; color: var(--muted); font-size: 12px; }
.drop-area {
  display: flex;
  min-height: 132px;
  margin-top: 14px;
  padding: 16px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: 1px dashed var(--primary);
  border-radius: 8px;
  background: var(--soft);
  text-align: center;
  overflow-wrap: anywhere;
  cursor: pointer;
}
.drop-area:focus-within { outline: 2px solid var(--primary); outline-offset: 2px; }
.file-input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.upload-icon {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border-radius: 6px;
  background: var(--selected);
  color: var(--primary);
  font-size: 20px;
}
.file-list { max-height: 115px; margin: 8px 0 0; padding: 0; overflow: auto; list-style: none; }
.file-list li { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.file-list img { width: 36px; height: 27px; object-fit: cover; border-radius: 3px; background: var(--soft); }
.file-list span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-list button { border: 0; background: none; color: var(--primary); font: inherit; cursor: pointer; }
.split-list { display: grid; gap: 8px; max-height: 45dvh; overflow-y: auto; }
.split-list label { display: grid; grid-template-columns: minmax(0, 1fr) 140px; align-items: center; gap: 12px; }
.split-list span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.demo-note { margin: 10px 0; color: var(--muted); font-size: 12px; }
.delete-description { margin: 0; color: var(--muted); line-height: 1.6; }
.delete-description strong { color: var(--text); }
.dialog-error { margin: 12px 0 0; color: #a42d3c; }
.check-row { display: flex; align-items: center; gap: 6px; margin-top: 12px; }
input[type="range"] { width: 100%; accent-color: var(--primary); }
output { color: var(--primary); }
.dialog-footer { display: flex; align-items: center; justify-content: flex-end; gap: 8px; padding: 13px 24px; border-top: 1px solid var(--line); background: var(--soft); }
.footer-note { margin-right: auto; color: var(--muted); font-size: 12px; }
.dialog-footer .button { white-space: nowrap; }
@media (max-width: 520px) {
  .dialog-header { padding-left: 16px; }
  .dialog-body, .dialog-footer { padding-left: 16px; padding-right: 16px; }
  .dialog-footer { flex-wrap: wrap; }
  .footer-note { flex-basis: 100%; }
}
</style>
