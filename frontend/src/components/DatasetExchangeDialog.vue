<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { downloadYolo, importDatasetArchive, importDatasetDirectory } from '../api/datasets'
import { taskLabels } from '../domain'
import type { Dataset, TaskType } from '../domain'
import LocalDirectoryPicker from './LocalDirectoryPicker.vue'

type Mode = 'import' | 'export'
type Source = 'native' | 'yolo' | 'local' | 'coco' | 'coco-local' | 'video'

const props = defineProps<{ initialMode: Mode; dataset?: Dataset; datasets: Dataset[] }>()
const emit = defineEmits<{ close: []; imported: [dataset: Dataset] }>()
const dialog = ref<HTMLDialogElement>()
const mode = ref(props.initialMode)
const datasetId = ref(props.dataset?.id ?? '')
const includeImages = ref(true)
const includeNegative = ref(true)
const source = ref<Source>('yolo')
const task = ref<TaskType>('detect')
const archive = ref<File>()
const directory = ref('')
const fileError = ref('')
const prepared = ref(false)
const busy = ref(false)
const sources: { id: Source; label: string; enabled?: boolean }[] = [
  { id: 'native', label: '原生工程归档（ZIP）' },
  { id: 'yolo', label: 'YOLO 数据集（ZIP）', enabled: true },
  { id: 'local', label: '本地 YOLO 目录（大数据集）', enabled: true },
  { id: 'coco', label: 'COCO 数据集（ZIP）', enabled: true },
  { id: 'coco-local', label: '本地 COCO 目录（大数据集）', enabled: true },
  { id: 'video', label: '视频抽帧' },
]

const dataset = computed(() => props.datasets.find(item => item.id === datasetId.value))
const localImport = computed(() => mode.value === 'import' && (source.value === 'local' || source.value === 'coco-local'))
const importFormat = computed(() => source.value === 'coco' || source.value === 'coco-local' ? 'coco' : 'yolo')
const importTasks = computed(() => Object.entries(taskLabels).filter(([key]) =>
  importFormat.value !== 'coco' || key === 'detect' || key === 'segment'))
const importReady = computed(() => localImport.value ? Boolean(directory.value.trim()) : Boolean(archive.value))
const classification = computed(() => dataset.value?.task === 'classify')
const preview = computed(() => {
  const images = dataset.value?.images.filter(image =>
    image.status === 'annotated' || (includeNegative.value && !classification.value && image.status === 'negative'),
  ) ?? []
  const splits = { train: 0, val: 0, test: 0 }
  const positiveSplits = new Set<string>()
  let annotations = 0
  let unassigned = 0
  for (const image of images) {
    if (image.split) {
      splits[image.split] += 1
      if (image.status === 'annotated') positiveSplits.add(image.split)
    }
    else unassigned += 1
    annotations += image.annotations.length
  }
  const missingSplits = ['train', 'val'].filter(split => !positiveSplits.has(split))
  return { images: images.length, splits, annotations, unassigned, missingSplits }
})
const classes = computed(() => dataset.value?.classes.map(item => item.name).join('、') || '—')
const fileSize = computed(() => {
  const bytes = archive.value?.size
  if (bytes === undefined) return '—'
  if (bytes < 1000) return bytes + ' B'
  return new Intl.NumberFormat('zh-CN', { style: 'unit', unit: bytes < 1000000 ? 'kilobyte' : 'megabyte', maximumFractionDigits: 1 })
    .format(bytes < 1000000 ? bytes / 1000 : bytes / 1000000)
})

onMounted(() => dialog.value?.showModal())
watch(importFormat, format => {
  if (format === 'coco' && task.value !== 'detect' && task.value !== 'segment') task.value = 'detect'
})
watch([mode, datasetId, includeImages, includeNegative, task, source, directory], () => {
  prepared.value = false
  fileError.value = ''
})

function selectFile(file?: File) {
  if (busy.value) return
  archive.value = undefined
  fileError.value = ''
  prepared.value = false
  if (!file) return
  if (!file.size || !/\.zip$/i.test(file.name)) {
    fileError.value = '请选择非空 ZIP 压缩包。'
    return
  }
  if (file.size > 256 * 1024 * 1024) {
    fileError.value = 'ZIP 文件不能超过 256 MiB。'
    return
  }
  archive.value = file
}

function pickFile(event: Event) {
  const input = event.target as HTMLInputElement
  selectFile(input.files?.[0])
  input.value = ''
}

function close() {
  if (!busy.value) emit('close')
}

async function exchange() {
  if (busy.value) return
  busy.value = true
  fileError.value = ''
  prepared.value = false
  try {
    if (mode.value === 'export' && dataset.value) {
      await downloadYolo(dataset.value.id, classification.value || includeImages.value, includeNegative.value)
      prepared.value = true
    } else if (mode.value === 'import' && importReady.value) {
      const imported = localImport.value
        ? await importDatasetDirectory(directory.value.trim(), task.value, importFormat.value)
        : await importDatasetArchive(archive.value!, task.value, importFormat.value)
      prepared.value = true
      emit('imported', imported)
    }
  } catch (error) {
    fileError.value = error instanceof Error ? error.message : '数据集交换失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <dialog ref="dialog" class="exchange" aria-labelledby="exchange-title" @cancel.prevent="close">
    <header class="exchange-header">
      <div>
        <div class="exchange-heading">
          <h2 id="exchange-title">数据集交换<span v-if="mode === 'export' && dataset"> · {{ dataset.name }}</span></h2>
          <span class="mode-tag">{{ mode === 'export' ? 'YOLO ZIP' : importFormat.toUpperCase() + (localImport ? ' · 本地目录' : ' ZIP') }}</span>
        </div>
        <p>导入数据集或导出 YOLO ZIP，保留图片分集和类别标注。</p>
      </div>
      <button class="close-exchange" type="button" aria-label="关闭数据集交换" :disabled="busy" @click="close">×</button>
    </header>

    <div class="exchange-body">
      <section class="exchange-controls" aria-label="数据集交换配置">
        <div class="exchange-switch" role="group" aria-label="交换方式">
          <button type="button" :aria-pressed="mode === 'export'" :disabled="busy" @click="mode = 'export'">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m-4-4 4 4 4-4M4 15v5h16v-5"/></svg>导出
          </button>
          <button type="button" :aria-pressed="mode === 'import'" :disabled="busy" @click="mode = 'import'">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V3m-4 4 4-4 4 4M4 15v5h16v-5"/></svg>导入
          </button>
        </div>

        <form v-if="mode === 'export'" class="exchange-form" @submit.prevent="exchange">
          <label v-if="!props.dataset">
            数据集
            <select v-model="datasetId" :disabled="busy" required>
              <option disabled value="">请选择要导出的数据集</option>
              <option v-for="item in datasets" :key="item.id" :value="item.id">{{ item.name }}</option>
            </select>
          </label>
          <label>
            导出格式
            <select aria-label="导出格式">
              <option>YOLO Dataset（ZIP）</option>
              <option disabled>COCO（待接入）</option>
              <option disabled>Pascal VOC（待接入）</option>
              <option disabled>DOTA 1.5（待接入）</option>
            </select>
          </label>
          <div class="export-options">
            <label><input type="checkbox" :checked="classification || includeImages" :disabled="busy || classification"
              @change="includeImages = ($event.target as HTMLInputElement).checked"> 打包原始图像</label>
            <label v-if="!classification"><input v-model="includeNegative" type="checkbox" :disabled="busy"> 包含已标记的负样本</label>
          </div>
          <p v-if="preview.unassigned" class="exchange-error">有 {{ preview.unassigned }} 张图片尚未分集，请先在数据集列表中分集。</p>
          <p v-else-if="dataset && preview.missingSplits.length" class="exchange-error">
            导出前请在 {{ preview.missingSplits.join('、') }} 分集各保存至少一张已标注图片。
          </p>
          <button class="button primary" type="submit"
            :disabled="!dataset || Boolean(preview.unassigned || preview.missingSplits.length) || busy">
            {{ busy ? '正在打包…' : '下载 YOLO ZIP' }}
          </button>
        </form>

        <form v-else class="exchange-form" @submit.prevent="exchange">
          <label>
            导入来源
            <select v-model="source" :disabled="busy">
              <option v-for="item in sources" :key="item.id" :value="item.id" :disabled="!item.enabled">
                {{ item.label }}{{ item.enabled ? '' : '（待接入）' }}
              </option>
            </select>
          </label>
          <label>
            任务类型
            <select v-model="task" :disabled="busy">
              <option v-for="[key, label] in importTasks" :key="key" :value="key">{{ label }}</option>
            </select>
            <small v-if="importFormat === 'coco'" class="task-note">
              同时提供 COCO 标注 JSON 和图片。{{ task === 'segment' ? '每个实例须有一个多边形轮廓。' : '检测任务读取 bbox。' }}
            </small>
            <small v-else-if="task === 'pose'" class="task-note">data.yaml 须包含 kpt_shape，各类别共用同一套关键点。</small>
            <small v-else-if="task === 'classify'" class="task-note">使用 train/类别/图片 和 val/类别/图片 目录结构。</small>
          </label>
          <LocalDirectoryPicker v-if="localImport" v-model="directory" :disabled="busy" />
          <label v-else class="exchange-drop" @dragover.prevent @drop.prevent="selectFile($event.dataTransfer?.files[0])">
            <input type="file" accept=".zip" :disabled="busy" @change="pickFile">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V3m-4 4 4-4 4 4M4 15v5h16v-5"/></svg>
            <strong>{{ archive?.name ?? '拖放或选择 ZIP 归档包' }}</strong>
            <small>ZIP 压缩包 · 最大 256 MiB</small>
          </label>
          <button class="button primary" type="submit" :disabled="!importReady || busy || prepared">{{ busy ? '正在导入…' : '导入数据集' }}</button>
        </form>

        <p v-if="fileError" class="exchange-error" role="alert">{{ fileError }}</p>
        <p v-else class="exchange-note" role="status">
          {{ prepared ? (mode === 'export' ? '已交给浏览器下载。' : '数据集已导入。') : (mode === 'export' ? '跳过未标注图片，按已保存的分集打包。' : localImport ? '后端直接读取本机目录并复制图片。大目录导入期间请保持页面打开。' : '归档内的分集和类别会随图片导入。') }}
        </p>
      </section>

      <section class="exchange-results" aria-labelledby="exchange-result-title">
        <div class="results-heading">
          <h3 id="exchange-result-title">{{ mode === 'export' ? '导出结果预览' : localImport ? '导入目录预览' : '导入文件预览' }}</h3>
          <span class="result-state" :class="{ prepared }">{{ busy ? '处理中' : prepared ? '已完成' : '待执行' }}</span>
        </div>

        <dl v-if="mode === 'export' && dataset" class="result-grid">
          <div class="full"><dt>文件格式</dt><dd class="path">YOLO ZIP</dd></div>
          <div><dt>图片数</dt><dd><strong>{{ preview.images.toLocaleString('zh-CN') }}</strong> <small>{{ includeImages || classification ? '张纳入打包范围' : '条图片记录 · 仅标注和配置' }}</small></dd></div>
          <div><dt>类别定义</dt><dd>{{ classes }}</dd></div>
          <div><dt>TRAIN / VAL / TEST 划分</dt><dd class="path">{{ preview.splits.train }} / {{ preview.splits.val }} / {{ preview.splits.test }}</dd></div>
          <div><dt>目标标注总数</dt><dd><strong>{{ preview.annotations.toLocaleString('zh-CN') }}</strong></dd></div>
          <div class="full"><dt>归档结构</dt><dd>{{ classification ? '分集 / 类别 / 图片' : 'data.yaml、labels 目录及可选的 images 目录' }}</dd></div>
        </dl>
        <dl v-else-if="localImport && directory.trim()" class="result-grid">
          <div class="full"><dt>本机目录</dt><dd class="path">{{ directory }}</dd></div>
          <div><dt>任务类型</dt><dd>{{ taskLabels[task] }}</dd></div>
          <div><dt>读取方式</dt><dd>由本地服务读取</dd></div>
        </dl>
        <dl v-else-if="mode === 'import' && archive && !localImport" class="result-grid">
          <div class="full"><dt>文件名称</dt><dd class="path">{{ archive.name }}</dd></div>
          <div><dt>任务类型</dt><dd>{{ taskLabels[task] }}</dd></div>
          <div><dt>文件大小</dt><dd class="path">{{ fileSize }}</dd></div>
        </dl>
        <p v-else class="exchange-empty">{{ mode === 'export' ? '选择数据集以查看当前图片、分集和标注。' : localImport ? '浏览本机磁盘，或粘贴数据集目录的绝对路径。' : '选择文件后可查看名称、类型和大小。' }}</p>

        <footer class="exchange-footer">
          <button class="button" type="button" :disabled="busy" @click="close">{{ prepared ? '完成' : '关闭' }}</button>
        </footer>
      </section>
    </div>
  </dialog>
</template>


<style scoped>
.exchange {
  width: min(1060px, calc(100vw - 40px));
  max-height: calc(100dvh - 40px);
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 20px 48px #1c2d4033;
}
.exchange::backdrop { background: #202e4566; backdrop-filter: blur(3px); }
.exchange-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 24px 28px 22px;
  border-bottom: 1px solid var(--line);
}
.exchange-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.exchange-heading h2 { margin: 0; font-size: 20px; color: #17243a; overflow-wrap: anywhere; }
.exchange-header p { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
.mode-tag, .result-state {
  flex: none;
  padding: 2px 8px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--selected);
  font-size: 12px;
}
.close-exchange {
  flex: 0 0 30px;
  height: 30px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font-size: 20px;
  line-height: 1;
}
.close-exchange:hover { background: var(--soft); }
.exchange-body { display: grid; grid-template-columns: minmax(0, 38fr) minmax(0, 62fr); min-height: 486px; }
.exchange-controls, .exchange-results { min-width: 0; display: flex; flex-direction: column; padding: 24px; }
.exchange-controls { border-right: 1px solid var(--line); }
.exchange-results { background: var(--soft); }
.exchange-switch {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 4px;
  padding: 4px;
  margin-bottom: 18px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #f0f4f8;
}
.exchange-switch button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 34px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
}
.exchange-switch button[aria-pressed="true"] { background: #294866; color: white; font-weight: 650; }
.exchange-switch svg, .exchange-drop svg { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.75; }
.exchange-form { display: grid; gap: 14px; margin-bottom: 16px; }
.exchange-form > label { display: block; font-weight: 600; }
.exchange-form small, .result-grid small { color: var(--muted); font-size: 12px; font-weight: normal; }
.task-note { display: block; margin-top: 5px; }
.exchange-form select {
  display: block;
  width: 100%;
  min-height: 38px;
  margin-top: 5px;
  padding: 6px 9px;
  border: 1px solid #c7d1de;
  border-radius: 8px;
  background: var(--soft);
  font-weight: normal;
}
.export-options { display: grid; gap: 6px; }
.export-options label { display: flex; align-items: center; gap: 6px; }
.export-options input { margin: 0; accent-color: var(--primary); }
.exchange-form > .button { min-height: 39px; border-radius: 8px; }
.exchange-form > .exchange-drop {
  position: relative;
  display: grid;
  justify-items: center;
  align-content: center;
  gap: 5px;
  min-height: 110px;
  padding: 10px;
  border: 1px dashed #a6b6c9;
  border-radius: 8px;
  background: var(--soft);
  cursor: pointer;
  text-align: center;
  overflow-wrap: anywhere;
}
.exchange-drop input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.exchange-drop:focus-within { outline: 2px solid var(--primary); outline-offset: 2px; }
.exchange-error { margin: 0; color: var(--danger); font-size: 13px; }
.exchange-note {
  margin: auto 0 0;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--soft);
  color: var(--muted);
  font-size: 12px;
}
.results-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 14px; }
.results-heading h3 { margin: 0; color: #17243a; font-size: 16px; }
.result-state { color: var(--muted); }
.result-state.prepared { border-color: #b4d7c1; background: #edf7f1; color: #28563d; }
.result-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 0; }
.result-grid > div {
  min-width: 0;
  padding: 10px 13px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
}
.result-grid .full { grid-column: 1 / -1; }
.result-grid dt { color: var(--muted); font-size: 12px; }
.result-grid dd { margin: 3px 0 0; overflow-wrap: anywhere; }
.result-grid strong { font-size: 17px; font-variant-numeric: tabular-nums; }
.path { font-family: "Cascadia Mono", Consolas, monospace; }
.exchange-empty { padding: 20px 12px; border: 1px dashed var(--line); border-radius: 8px; color: var(--muted); font-size: 12px; }
.exchange-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 12px;
}
@media (max-width: 690px) {
  .exchange-body { grid-template-columns: minmax(0, 1fr); }
  .exchange-header, .exchange-controls, .exchange-results { padding: 16px; }
  .exchange-controls { border-right: 0; border-bottom: 1px solid var(--line); }
  .exchange-footer { margin-top: 14px; }
}
</style>

