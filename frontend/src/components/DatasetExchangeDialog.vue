<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { downloadYolo, importDatasetArchive, importDatasetDirectory } from '../api/datasets'
import type { SkippedSample } from '../api/datasets'
import { selectableDatasetTasks, taskLabels } from '../domain'
import type { Dataset, SelectableDatasetTask } from '../domain'
import LocalDirectoryPicker from './LocalDirectoryPicker.vue'

type Mode = 'import' | 'export'
type Source = 'yolo' | 'coco' | 'local'

const props = defineProps<{ initialMode: Mode; dataset?: Dataset; datasets: Dataset[] }>()
const emit = defineEmits<{ close: []; imported: [dataset: Dataset] }>()
const dialog = ref<HTMLDialogElement>()
const mode = ref(props.initialMode)
const datasetId = ref(props.dataset?.id ?? '')
const includeImages = ref(true)
const includeNegative = ref(true)
const source = ref<Source>('yolo')
const localFormat = ref<'yolo' | 'coco'>('yolo')
const importName = ref('')
const task = ref<SelectableDatasetTask>('detect')
const skipInvalid = ref(false)
const archive = ref<File>()
const fileInput = ref<HTMLInputElement>()
const directory = ref('')
const fileError = ref('')
const prepared = ref(false)
const busy = ref(false)
const importResult = ref<{ name: string; count: number; skipped: SkippedSample[] }>()
const sources: { id: Source; label: string; hint: string; icon: string }[] = [
  { id: 'yolo', label: 'YOLO 数据集', hint: 'ZIP · data.yaml、images、labels', icon: 'M5 5h14v14H5z' },
  { id: 'coco', label: 'COCO 数据集', hint: 'ZIP · COCO 标注 JSON 与图片', icon: 'M4 4h16v16H4zM4 9h16M4 15h16M9 4v16M15 4v16' },
  { id: 'local', label: '本地文件夹直读', hint: 'YOLO / COCO · 适合大型数据集', icon: 'M3 6h7l2 2h9v11H3zM12 11v5m-2.5-2.5h5' },
]
const directoryExamples = {
  yolo: {
    tree: 'yolo_dataset/\n├── data.yaml\n├── images/\n│   ├── train/sample01.jpg\n│   └── val/sample02.jpg\n└── labels/\n    ├── train/sample01.txt\n    └── val/sample02.txt',
    note: '选择 yolo_dataset。data.yaml 指定分集路径和类别，标注文件与图片同名。',
  },
  classify: {
    tree: 'yolo_classification/\n├── train/coal/sample01.jpg\n├── train/gangue/sample02.jpg\n├── val/coal/sample03.jpg\n└── val/gangue/sample04.jpg',
    note: '选择 yolo_classification。分集下的子目录名就是类别名。',
  },
  coco: {
    tree: 'coco_dataset/\n├── annotations/\n│   ├── instances_train2017.json\n│   └── instances_val2017.json\n├── train2017/sample01.jpg\n└── val2017/sample02.jpg',
    note: '选择 coco_dataset。标注 JSON 的 images[].file_name 必须指向目录中的对应图片。',
  },
}

const dataset = computed(() => props.datasets.find(item => item.id === datasetId.value))
const localImport = computed(() => source.value === 'local')
const importFormat = computed(() => source.value === 'local' ? localFormat.value : source.value)
const sourceLabel = computed(() => sources.find(item => item.id === source.value)!.label)
const directoryExample = computed(() => directoryExamples[importFormat.value === 'coco' ? 'coco' : task.value === 'classify' ? 'classify' : 'yolo'])
const inferredName = computed(() => localImport.value
  ? directory.value.trim().split(/[\\/]/).filter(Boolean).at(-1)
  : archive.value?.name.replace(/\.zip$/i, ''))
const importTasks = computed(() => selectableDatasetTasks.filter(key =>
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
  archive.value = undefined
  if (format === 'coco' && task.value !== 'detect' && task.value !== 'segment') task.value = 'detect'
})
watch([mode, datasetId, includeImages, includeNegative, task, source, directory, localFormat, importName, skipInvalid], () => {
  prepared.value = false
  fileError.value = ''
  importResult.value = undefined
})

function selectSource(next: Source) {
  if (source.value === next) return
  if (next === 'local') localFormat.value = importFormat.value
  source.value = next
}

function selectFile(file?: File) {
  if (busy.value) return
  archive.value = undefined
  fileError.value = ''
  prepared.value = false
  importResult.value = undefined
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
  if (busy.value || (mode.value === 'import' && (!importReady.value || prepared.value))) return
  busy.value = true
  fileError.value = ''
  prepared.value = false
  try {
    if (mode.value === 'export' && dataset.value) {
      await downloadYolo(dataset.value.id, classification.value || includeImages.value, includeNegative.value)
      prepared.value = true
    } else if (mode.value === 'import' && importReady.value) {
      const name = importName.value.trim() || undefined
      const imported = localImport.value
        ? await importDatasetDirectory(directory.value.trim(), task.value, importFormat.value, skipInvalid.value, name)
        : await importDatasetArchive(archive.value!, task.value, importFormat.value, skipInvalid.value, name)
      importResult.value = { name: imported.dataset.name, count: imported.dataset.images.length, skipped: imported.skippedSamples }
      prepared.value = true
      emit('imported', imported.dataset)
    }
  } catch (error) {
    fileError.value = error instanceof Error ? error.message : '数据集交换失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <dialog ref="dialog" class="exchange" :class="{ 'import-dialog': mode === 'import' }"
    aria-labelledby="exchange-title" @cancel.prevent="close">
    <template v-if="mode === 'import'">
      <header class="exchange-header import-header">
        <div>
          <div class="import-caption path"><span>IMPORT CENTER</span> / DATASET INGESTION PIPELINE</div>
          <div class="exchange-heading"><h2 id="exchange-title">导入数据集</h2></div>
          <p>选择数据来源，将图片、类别、标注和分集导入工作台。</p>
        </div>
        <button class="close-exchange" type="button" aria-label="关闭导入数据集" :disabled="busy" @click="close">×</button>
      </header>

      <div class="import-body">
        <aside class="import-sources">
          <h3>导入来源</h3>
          <div class="import-source-list" role="group" aria-label="导入来源">
            <button v-for="item in sources" :key="item.id" type="button" class="import-source"
              :aria-pressed="source === item.id" :disabled="busy" @click="selectSource(item.id)">
              <span class="source-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path :d="item.icon" /></svg></span>
              <span><strong>{{ item.label }}</strong><small>{{ item.hint }}</small></span>
            </button>
            <button class="import-source" type="button" disabled>
              <span class="source-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="m10 8 6 4-6 4z" /></svg></span>
              <span><strong>视频文件</strong><small>抽帧导入 · 待接入</small></span>
            </button>
          </div>
          <p class="exchange-note">导入时保留源数据中的分集和类别标注。</p>
        </aside>

        <form id="dataset-import-form" class="import-form exchange-form" @submit.prevent="exchange">
          <div class="import-section-heading">
            <span class="import-step">1</span>
            <h3>{{ sourceLabel }}</h3>
            <small>{{ localImport ? '读取已解压的本机目录' : '上传 ZIP 压缩包' }}</small>
          </div>
          <div class="import-fields">
            <label>
              数据集名称
              <input v-model="importName" type="text" maxlength="120" :disabled="busy"
                :placeholder="inferredName || '留空时使用文件名或目录名'">
            </label>
            <label>
              任务类型
              <select v-model="task" :disabled="busy">
                <option v-for="key in importTasks" :key="key" :value="key">{{ taskLabels[key] }}</option>
              </select>
            </label>
          </div>

          <div v-if="localImport" class="directory-import">
            <div class="directory-mode">
              <strong>目录格式</strong>
              <div class="directory-formats" role="group" aria-label="目录格式">
                <button v-for="format in (['yolo', 'coco'] as const)" :key="format" class="button" type="button"
                  :aria-pressed="localFormat === format" :disabled="busy" @click="localFormat = format">{{ format.toUpperCase() }}</button>
              </div>
              <button class="button" type="button" :disabled="busy" @click="selectSource(importFormat)">改用 ZIP 上传</button>
            </div>
            <LocalDirectoryPicker v-model="directory" :disabled="busy" />
            <details class="directory-example" open>
              <summary>{{ importFormat.toUpperCase() }} 示例目录</summary>
              <pre class="path">{{ directoryExample.tree }}</pre>
              <p>{{ directoryExample.note }}</p>
              <p v-if="importFormat === 'yolo' && task !== 'classify'"><code>data.yaml</code> 示例</p>
              <pre v-if="importFormat === 'yolo' && task !== 'classify'" class="path">train: images/train
val: images/val
names: [coal, gangue]</pre>
            </details>
          </div>
          <div v-else class="import-drop" @dragover.prevent @drop.prevent="selectFile($event.dataTransfer?.files[0])">
            <input ref="fileInput" type="file" accept=".zip" hidden :disabled="busy" @change="pickFile">
            <span class="upload-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h8l4 4v14H6zM14 3v5h4M12 18v-7m-3 3 3-3 3 3" /></svg></span>
            <strong>拖放 ZIP 压缩包到此处</strong>
            <small>{{ importFormat === 'coco' ? '压缩包内须包含 COCO 标注 JSON 和对应图片。' : task === 'classify' ? '按分集和类别子目录存放图片。' : '压缩包内须包含 data.yaml、图片和对应标签。' }}</small>
            <div class="upload-actions">
              <button class="button primary" type="button" :disabled="busy" @click="fileInput?.click()">选择 ZIP 文件</button>
              <button class="button" type="button" :disabled="busy" @click="selectSource('local')">选择本地目录</button>
            </div>
            <small class="upload-limit">单包上限 256 MiB · 大数据集可使用本地文件夹直读</small>
          </div>

          <div v-if="importFormat === 'coco'" class="exchange-options">
            <label><input v-model="skipInvalid" type="checkbox" :disabled="busy"> 跳过有问题的样本</label>
            <small>校验失败时排除整张图片，导入后可查看原因。{{ task === 'segment' ? '分割任务读取多边形轮廓。' : '检测任务读取 bbox。' }}</small>
          </div>
          <p v-if="fileError" class="exchange-error" role="alert">{{ fileError }}</p>
          <section class="import-preview" aria-labelledby="import-preview-title">
            <div class="results-heading">
              <h3 id="import-preview-title">{{ importResult ? '导入结果' : localImport ? '导入目录预览' : '导入文件预览' }}</h3>
              <span class="result-state" :class="{ prepared }" role="status">
                {{ busy ? '正在导入…' : prepared ? '已导入' : fileError ? '请检查' : importReady ? '就绪（待执行）' : '待选择' }}
              </span>
            </div>
            <template v-if="importResult">
              <div class="import-preview-item">
                <strong>{{ importResult.name }}</strong>
                <small>已导入 {{ importResult.count.toLocaleString('zh-CN') }} 张图片<span v-if="importFormat === 'coco'"> · 已排除 {{ importResult.skipped.length.toLocaleString('zh-CN') }} 张</span></small>
              </div>
              <details v-if="importResult.skipped.length" class="skipped-samples">
                <summary>查看排除明细</summary>
                <ul>
                  <li v-for="(sample, index) in importResult.skipped" :key="index">
                    <strong>{{ sample.filename }}</strong>
                    <small>{{ sample.manifest }} · {{ sample.reason }}</small>
                  </li>
                </ul>
              </details>
            </template>
            <div v-else-if="importReady" class="import-preview-item">
              <strong class="path">{{ localImport ? directory : archive?.name }}</strong>
              <small>{{ localImport ? '由本地服务读取' : fileSize }} · {{ taskLabels[task] }} · 开始导入时校验</small>
              <button v-if="!localImport" class="close-exchange" type="button" aria-label="移除 ZIP 文件"
                :disabled="busy" @click="selectFile()">×</button>
            </div>
            <p v-else class="import-empty">{{ localImport ? '浏览或输入数据集根目录的绝对路径。' : '选择 ZIP 文件后可在这里查看文件信息。' }}</p>
          </section>
        </form>
      </div>

      <footer class="import-footer">
        <small>{{ busy && localImport ? '正在读取本机目录，请保持页面打开。' : '文件仅导入到本机受管数据目录。' }}</small>
        <button v-if="initialMode === 'export'" class="button" type="button" :disabled="busy" @click="mode = 'export'">返回导出</button>
        <button class="button" type="button" :disabled="busy" @click="close">{{ prepared ? '完成' : '取消' }}</button>
        <button class="button primary" type="submit" form="dataset-import-form" :disabled="!importReady || busy || prepared">
          {{ busy ? '正在导入…' : '开始导入' }}
        </button>
      </footer>
    </template>

    <template v-else>
    <header class="exchange-header">
      <div>
        <div class="exchange-heading">
          <h2 id="exchange-title">数据集交换<span v-if="dataset"> · {{ dataset.name }}</span></h2>
          <span class="mode-tag">YOLO ZIP</span>
        </div>
        <p>导入数据集或导出 YOLO ZIP，保留图片分集和类别标注。</p>
      </div>
      <button class="close-exchange" type="button" aria-label="关闭数据集交换" :disabled="busy" @click="close">×</button>
    </header>

    <div class="exchange-body">
      <section class="exchange-controls" aria-label="数据集交换配置">
        <div class="exchange-switch" role="group" aria-label="交换方式">
          <button type="button" aria-pressed="true" :disabled="busy">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m-4-4 4 4 4-4M4 15v5h16v-5"/></svg>导出
          </button>
          <button type="button" aria-pressed="false" :disabled="busy" @click="mode = 'import'">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V3m-4 4 4-4 4 4M4 15v5h16v-5"/></svg>导入
          </button>
        </div>

        <form class="exchange-form" @submit.prevent="exchange">
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
          <div class="exchange-options">
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

        <p v-if="fileError" class="exchange-error" role="alert">{{ fileError }}</p>
        <p v-else class="exchange-note" role="status">
          {{ prepared ? '已交给浏览器下载。' : '跳过未标注图片，按已保存的分集打包。' }}
        </p>
      </section>

      <section class="exchange-results" aria-labelledby="exchange-result-title">
        <div class="results-heading">
          <h3 id="exchange-result-title">导出结果预览</h3>
          <span class="result-state" :class="{ prepared }">{{ busy ? '处理中' : prepared ? '已完成' : '待执行' }}</span>
        </div>

        <dl v-if="dataset" class="result-grid">
          <div class="full"><dt>文件格式</dt><dd class="path">YOLO ZIP</dd></div>
          <div><dt>图片数</dt><dd><strong>{{ preview.images.toLocaleString('zh-CN') }}</strong> <small>{{ includeImages || classification ? '张纳入打包范围' : '条图片记录 · 仅标注和配置' }}</small></dd></div>
          <div><dt>类别定义</dt><dd>{{ classes }}</dd></div>
          <div><dt>TRAIN / VAL / TEST 划分</dt><dd class="path">{{ preview.splits.train }} / {{ preview.splits.val }} / {{ preview.splits.test }}</dd></div>
          <div><dt>目标标注总数</dt><dd><strong>{{ preview.annotations.toLocaleString('zh-CN') }}</strong></dd></div>
          <div class="full"><dt>归档结构</dt><dd>{{ classification ? '分集 / 类别 / 图片' : 'data.yaml、labels 目录及可选的 images 目录' }}</dd></div>
        </dl>
        <p v-else class="exchange-empty">选择数据集以查看当前图片、分集和标注。</p>

        <footer class="exchange-footer">
          <button class="button" type="button" :disabled="busy" @click="close">{{ prepared ? '完成' : '关闭' }}</button>
        </footer>
      </section>
    </div>
    </template>
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
.exchange-switch svg { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.75; }
.exchange-form { display: grid; gap: 14px; margin-bottom: 16px; }
.exchange-form > label { display: block; font-weight: 600; }
.exchange-form small, .result-grid small { color: var(--muted); font-size: 12px; font-weight: normal; }
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
.exchange-options { display: grid; gap: 6px; }
.exchange-options label { display: flex; align-items: center; gap: 6px; }
.exchange-options input { margin: 0; accent-color: var(--primary); }
.exchange-form > .button { min-height: 39px; border-radius: 8px; }
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
.skipped-samples { margin: 12px 0; overflow-wrap: anywhere; font-size: 13px; }
.skipped-samples summary { cursor: pointer; }
.skipped-samples ul { max-height: 240px; overflow: auto; margin: 8px 0 0; padding-left: 22px; }
.skipped-samples li { margin-bottom: 8px; }
.skipped-samples small { display: block; color: var(--muted); }
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
.import-dialog { width: min(960px, calc(100vw - 32px)); }
.import-dialog[open] {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
}
.import-header { padding: 23px 32px 19px; background: #f9fafb; }
.import-header .exchange-heading h2 { margin-top: 6px; font-size: 24px; }
.import-caption { color: var(--muted); font-size: 11px; letter-spacing: .04em; }
.import-caption span { padding: 2px 6px; border: 1px solid var(--line); border-radius: 3px; background: var(--selected); }
.import-header .close-exchange { border: 1px solid var(--line); border-radius: 50%; }
.import-body { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); overflow: auto; }
.import-sources {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px;
  border-right: 1px solid var(--line);
  background: var(--soft);
}
.import-sources h3 { margin: 0; color: var(--muted); font-size: 13px; }
.import-source-list { display: grid; gap: 10px; }
.import-source {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  align-items: center;
  gap: 11px;
  min-height: 62px;
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  text-align: left;
  background: var(--surface);
}
.import-source:not(:disabled):hover { border-color: var(--primary); }
.import-source[aria-pressed="true"] {
  border-color: var(--primary);
  box-shadow: inset 0 0 0 1px var(--primary);
  background: var(--selected);
}
.import-source:disabled { opacity: .65; }
.source-icon, .upload-icon, .import-step {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 6px;
  background: var(--selected);
  color: var(--primary);
}
.import-source[aria-pressed="true"] .source-icon, .import-step { background: #344e68; color: white; }
.import-source svg, .upload-icon svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.7; }
.import-source small, .import-preview-item small { display: block; margin-top: 2px; color: var(--muted); font-size: 12px; }
.import-form { align-content: start; gap: 18px; margin: 0; padding: 24px 28px; }
.import-section-heading, .directory-mode, .directory-formats, .upload-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.import-section-heading h3 { margin: 0; font-size: 16px; }
.import-step { width: 24px; height: 24px; border-radius: 50%; font-size: 12px; }
.import-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.import-fields label { min-width: 0; font-size: 13px; font-weight: 600; }
.import-fields input {
  display: block;
  width: 100%;
  min-height: 38px;
  margin-top: 5px;
  padding: 6px 9px;
  border: 1px solid #c7d1de;
  border-radius: 8px;
  font-weight: normal;
}
.import-drop, .directory-import {
  min-width: 0;
  padding: 16px;
  border: 1px dashed #a9bed5;
  border-radius: 9px;
  background: var(--soft);
}
.import-drop {
  display: grid;
  justify-items: center;
  align-content: center;
  gap: 6px;
  min-height: 214px;
  text-align: center;
}
.upload-icon { width: 46px; height: 46px; margin-bottom: 3px; }
.upload-icon svg { width: 24px; height: 24px; }
.upload-actions { justify-content: center; margin: 5px 0; }
.upload-limit { padding: 2px 8px; border: 1px solid var(--line); border-radius: 12px; }
.directory-import { display: grid; gap: 12px; }
.directory-formats button[aria-pressed="true"] { border-color: var(--primary); background: var(--selected); color: #344e68; }
.directory-mode > .button { margin-left: auto; }
.directory-example {
  min-width: 0;
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  font-size: 12px;
}
.directory-example summary { font-weight: 600; cursor: pointer; }
.directory-example pre { margin: 6px 0 0; padding: 7px 9px; overflow: auto; background: var(--soft); }
.directory-example p { margin: 6px 0 0; color: var(--muted); }
.import-preview { min-width: 0; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--soft); }
.import-preview .results-heading { margin-bottom: 8px; }
.import-preview h3 { font-size: 13px; }
.import-preview-item {
  position: relative;
  padding: 8px 40px 8px 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface);
  overflow-wrap: anywhere;
}
.import-preview-item button { position: absolute; top: 7px; right: 6px; width: 28px; height: 28px; }
.import-empty { margin: 0; color: var(--muted); font-size: 12px; }
.import-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px 32px;
  border-top: 1px solid var(--line);
  background: var(--soft);
}
.import-footer small { margin-right: auto; color: var(--muted); }
.import-footer .primary { min-width: 104px; }
@media (max-width: 690px) {
  .exchange-body { grid-template-columns: minmax(0, 1fr); }
  .exchange-header, .exchange-controls, .exchange-results { padding: 16px; }
  .exchange-controls { border-right: 0; border-bottom: 1px solid var(--line); }
  .exchange-footer { margin-top: 14px; }
  .import-body { grid-template-columns: minmax(0, 1fr); }
  .import-sources { padding: 14px; border-right: 0; border-bottom: 1px solid var(--line); }
  .import-source-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .import-source { grid-template-columns: minmax(0, 1fr); }
  .import-source .source-icon { display: none; }
  .import-form, .import-footer { padding: 14px; }
}
</style>

