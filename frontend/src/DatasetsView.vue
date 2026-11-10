<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Dataset, DatasetAction, DatasetReport, ReportIssue, SelectableDatasetTask } from './domain'
import { datasetCounts, selectableDatasetTasks, taskLabels } from './domain'
import DatasetQualityReport from './components/DatasetQualityReport.vue'
import DatasetReportState from './components/DatasetReportState.vue'
import DatasetValidationReport from './components/DatasetValidationReport.vue'

type Task = Dataset['task']
const props = defineProps<{ datasets: Dataset[]; report?: DatasetReport }>()
const emit = defineEmits<{
  create: []
  import: []
  action: [action: DatasetAction, dataset: Dataset]
  'close-report': []
  'refresh-report': []
  'open-image': [dataset: Dataset, imageId: string]
  'review-pair': [dataset: Dataset, issue: ReportIssue, issues: ReportIssue[]]
}>()

const taskShort: Record<SelectableDatasetTask, string> = { detect: '检测', obb: 'OBB', segment: '分割', classify: '分类' }
const taskIcon: Record<Task, string> = {
  detect: 'M4 6h12v10H4z M8 4V2h12v10h-2',
  obb: 'm12 3 9 9-9 9-9-9z M8 12h8m-4-4v8',
  segment: 'M6 5h3v3H6z M15 4h3v3h-3z M14 16h3v3h-3z M5 14h3v3H5z M9 6l6-1m2 2-1 9m-2 1-6-1m-1-2V8',
  classify: 'm12 3 4 6H8z M4 14h6v6H4z M20 17a3 3 0 1 1-6 0 3 3 0 0 1 6 0z',
  pose: 'M12 7v6m-5-3 5-1 5 1m-8 10 3-7 3 7M12 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4z',
}
const operations: { action: DatasetAction; label: string }[] = [
  { action: 'assistant', label: '询问助手' },
  { action: 'train', label: '训练' },
  { action: 'auto', label: '自动标注' },
  { action: 'export', label: '导出数据集' },
  { action: 'splits', label: '调整分集' },
  { action: 'duplicates', label: '精确重复' },
  { action: 'validate', label: '运行校验' },
  { action: 'quality', label: '质量报告' },
  { action: 'excluded', label: '已排除样本' },
  { action: 'delete', label: '删除' },
]
const requiresImages = new Set<DatasetAction>(['auto', 'export', 'splits', 'duplicates', 'validate', 'quality'])
const query = ref('')
const selectedTask = ref<SelectableDatasetTask | 'all'>('all')
const page = ref(1)
const pageSize = 9
const preferenceKey = 'inspection-workbench:datasets-view'
function initialView() {
  try {
    return localStorage.getItem(preferenceKey) === 'list' ? 'list' : 'cards'
  } catch {
    return 'cards'
  }
}
const view = ref<'list' | 'cards'>(initialView())
const menuId = ref<string>()
const reportPage = ref(1)
const reportPageSize = 5
const reviewFilter = ref<'unconfirmed' | 'confirmed'>('unconfirmed')
const reportIssues = computed(() => props.report?.issues ?? [])
const confirmedCount = computed(() => reportIssues.value.filter(issue => issue.review_status === 'confirmed').length)
const filteredIssues = computed(() => reportIssues.value.filter(issue =>
  (issue.review_status === 'confirmed') === (reviewFilter.value === 'confirmed')))
const reportMessageCount = computed(() => reportIssues.value.length ? filteredIssues.value.length : props.report?.messages?.length ?? 0)
const reportPageCount = computed(() => Math.max(1, Math.ceil(reportMessageCount.value / reportPageSize)))
const currentReportPage = computed(() => Math.min(reportPage.value, reportPageCount.value))
const reportOffset = computed(() => (currentReportPage.value - 1) * reportPageSize)
const numberFormat = new Intl.NumberFormat('zh-CN')
const dateFormat = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
})
const formatNumber = (count: number) => numberFormat.format(count)
function formatDate(value: Dataset['createdAt']) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : dateFormat.format(date)
}
function percent(annotated: number, images: number) {
  return images ? Math.min(100, annotated / images * 100) : 0
}
const rows = computed(() => props.datasets.map(dataset => {
  const counts = datasetCounts(dataset)
  return { dataset, ...counts, progress: percent(counts.annotated, counts.images) }
}))
const filtered = computed(() => {
  const term = query.value.trim().toLocaleLowerCase()
  return rows.value.filter(({ dataset }) =>
    (selectedTask.value === 'all' || dataset.task === selectedTask.value)
    && dataset.name.toLocaleLowerCase().includes(term),
  )
})
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const currentPage = computed(() => Math.min(page.value, pageCount.value))
const offset = computed(() => (currentPage.value - 1) * pageSize)
const visibleRows = computed(() => filtered.value.slice(offset.value, offset.value + pageSize))
const totals = computed(() => {
  let images = 0
  let annotated = 0
  const taskCounts: Record<Task, number> = { detect: 0, obb: 0, segment: 0, classify: 0, pose: 0 }
  for (const row of rows.value) {
    images += row.images
    annotated += row.annotated
    taskCounts[row.dataset.task] += 1
  }
  return { images, annotated, taskCounts, progress: percent(annotated, images) }
})

watch([query, selectedTask], () => { page.value = 1; menuId.value = undefined })
watch(pageCount, maximum => { page.value = Math.min(page.value, maximum) })
watch([currentPage, view], () => { menuId.value = undefined })
watch([() => props.report?.datasetId, () => props.report?.kind], () => {
  reviewFilter.value = 'unconfirmed'
  reportPage.value = 1
})
watch(reviewFilter, () => { reportPage.value = 1 })
watch(reportPageCount, maximum => { reportPage.value = Math.min(reportPage.value, maximum) })
watch(view, value => {
  try {
    localStorage.setItem(preferenceKey, value)
  } catch {
    // The view can still be switched when browser storage is unavailable.
  }
})

function mainLabel(images: number, annotated: number) {
  if (!images) return '添加图片'
  if (annotated >= images) return '查看标注'
  return annotated ? '继续标注' : '开始标注'
}
function runAction(action: DatasetAction, dataset: Dataset) {
  menuId.value = undefined
  if (props.report?.datasetId === dataset.id && props.report.kind === action) {
    emit('close-report')
  } else {
    emit('action', action, dataset)
  }
}
function actionLabel(action: DatasetAction, label: string, dataset: Dataset) {
  if (props.report?.datasetId !== dataset.id || props.report.kind !== action) return label
  if (action === 'validate') return '收起校验'
  if (action === 'duplicates') return '收起重复图'
  return '收起报告'
}
function actionExpanded(action: DatasetAction, dataset: Dataset) {
  if (action === 'validate' || action === 'duplicates' || action === 'quality') {
    return props.report?.datasetId === dataset.id && props.report.kind === action
  }
  return undefined
}
function canReview(issue: ReportIssue) {
  return props.report?.status === 'ready' && !props.report.stale && issue.code === 'duplicate_exact'
    && issue.review_status === 'pending' && Boolean(issue.image_sha256 && issue.related_image_sha256)
}
function closeMenuOutside(event: FocusEvent) {
  const region = event.currentTarget as HTMLElement
  if (!region.contains(event.relatedTarget as Node | null)) menuId.value = undefined
}
</script>

<template>
  <section class="datasets-view">
    <header class="datasets-heading">
      <div>
        <div class="heading-line">
          <h1>数据集</h1>
          <span class="index-label">VISION-INDEX-01</span>
        </div>
        <p>导入图片或已有 YOLO 数据集，管理训练所需的视觉数据</p>
      </div>
      <div class="heading-actions">
        <button class="button" type="button" @click="emit('import')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3h9l5 5v13H5z M14 3v6h5 M12 17v-5m-3 3 3-3 3 3"/></svg>
          导入数据集
        </button>
        <button class="button primary" type="button" @click="emit('create')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
          新建数据集
        </button>
      </div>
    </header>

    <div class="datasets-toolbar">
      <label class="search-box">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0zm-1 5 5 5"/></svg>
        <input v-model="query" type="search" aria-label="搜索数据集" placeholder="搜索数据集…">
      </label>
      <div class="segmented task-filter" role="group" aria-label="任务类型">
        <button type="button" :aria-pressed="selectedTask === 'all'" @click="selectedTask = 'all'">全部</button>
        <button v-for="task in selectableDatasetTasks" :key="task" type="button" :aria-pressed="selectedTask === task" @click="selectedTask = task">
          {{ taskLabels[task] }}
        </button>
      </div>
      <div class="toolbar-right">
        <div class="segmented view-toggle" role="group" aria-label="数据集视图">
          <button type="button" :aria-pressed="view === 'list'" @click="view = 'list'">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6h11M9 12h11M9 18h11M4 6h1M4 12h1M4 18h1"/></svg>列表
          </button>
          <button type="button" :aria-pressed="view === 'cards'" @click="view = 'cards'">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z"/></svg>卡片
          </button>
        </div>
        <span class="match-count">共 {{ filtered.length }} 个数据集</span>
      </div>
    </div>

    <div v-if="!visibleRows.length" class="empty-state">
      <strong>{{ datasets.length ? '未找到匹配的数据集' : '暂无数据集' }}</strong>
      <p>{{ datasets.length ? '尝试其他关键词或任务类型。' : '新建一个数据集，或导入已有数据。' }}</p>
      <button v-if="datasets.length" class="button" type="button" @click="query = ''; selectedTask = 'all'">清除筛选</button>
      <button v-else class="button primary" type="button" @click="emit('create')">新建数据集</button>
    </div>

    <div v-else :class="['dataset-results', { 'list-view': view === 'list', 'card-view': view === 'cards' }]" :role="view === 'list' ? 'table' : undefined" aria-label="数据集">
      <div v-if="view === 'list'" class="table-header" role="row">
        <span role="columnheader">数据集名称</span><span role="columnheader">任务类型</span>
        <span class="num-heading" role="columnheader">图片数</span><span class="num-heading" role="columnheader">类别数</span>
        <span role="columnheader">标注进度</span><span class="actions-heading" role="columnheader">操作</span>
      </div>

      <div v-for="row in visibleRows" :key="row.dataset.id" class="dataset-entry" :role="view === 'list' ? 'rowgroup' : undefined">
        <div class="dataset-row" :role="view === 'list' ? 'row' : undefined">
          <div class="identity" :role="view === 'list' ? 'cell' : undefined">
            <span class="task-icon">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="taskIcon[row.dataset.task]"/></svg>
            </span>
            <div class="identity-text">
              <div class="name-line">
                <strong :title="row.dataset.name">{{ row.dataset.name }}</strong>
              </div>
              <small v-if="view === 'cards'">{{ taskLabels[row.dataset.task] }} · {{ formatDate(row.dataset.createdAt) }}</small>
              <small v-else>创建于 {{ formatDate(row.dataset.createdAt) }}</small>
            </div>
            <button v-if="view === 'cards' && row.images" class="add-shortcut" type="button" @click="runAction('add', row.dataset)">+ 添加图片</button>
          </div>
          <span v-if="view === 'list'" class="task-cell" role="cell">{{ taskLabels[row.dataset.task] }}</span>

          <div class="numeric" :role="view === 'list' ? 'cell' : undefined">
            <span v-if="view === 'cards'" class="metric-label">图片</span>
            <div><strong>{{ formatNumber(row.images) }}</strong> <small>张</small></div>
          </div>
          <div class="numeric" :role="view === 'list' ? 'cell' : undefined">
            <span v-if="view === 'cards'" class="metric-label">类别</span>
            <div><strong>{{ formatNumber(row.classes) }}</strong> <small>类</small></div>
          </div>
          <div class="progress-cell" :role="view === 'list' ? 'cell' : undefined">
            <div class="progress-caption">
              <span v-if="view === 'cards'" class="metric-label">标注进度</span>
              <span v-if="!row.images" class="muted">等待导入</span>
              <span v-else-if="row.progress >= 100" class="completed">✓ 已完成 100%</span>
              <span v-else class="progress-numbers">{{ formatNumber(row.annotated) }} / {{ formatNumber(row.images) }}（{{ row.progress.toFixed(1) }}%）</span>
            </div>
            <progress :value="row.progress" max="100" :class="{ complete: row.progress >= 100 }" :aria-label="`标注进度 ${row.progress.toFixed(1)}%`"></progress>
          </div>

          <div class="row-actions" :role="view === 'list' ? 'cell' : undefined">
            <button class="button primary main-action" type="button" @click="runAction(row.images ? 'annotate' : 'add', row.dataset)">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="row.images ? 'M4 5h16M4 10h11M4 15h6m2 5 1-4 6-6 3 3-6 6z' : 'M4 6h9m-9 0v13h16v-7M18 3v8m-4-4h8M5 16l4-4 3 3 2-2 5 5'"/></svg>
              {{ mainLabel(row.images, row.annotated) }}
            </button>
            <div v-if="view === 'list'" class="menu-region" @focusout="closeMenuOutside" @keydown.esc="menuId = undefined">
              <button class="button more-button" type="button" :aria-label="`${row.dataset.name} 的更多操作`" :aria-expanded="menuId === row.dataset.id"
                @click="menuId = menuId === row.dataset.id ? undefined : row.dataset.id">⋯</button>
              <div v-if="menuId === row.dataset.id" class="action-menu">
                <button v-if="row.images" type="button" @click="runAction('add', row.dataset)">添加图片</button>
                <button v-for="item in operations" :key="item.action" type="button" :class="{ destructive: item.action === 'delete' }"
                  :aria-expanded="actionExpanded(item.action, row.dataset)"
                  :disabled="!row.images && requiresImages.has(item.action)" @click="runAction(item.action, row.dataset)">
                  {{ actionLabel(item.action, item.label, row.dataset) }}
                </button>
              </div>
            </div>
          </div>
          <div v-if="view === 'cards'" class="card-actions">
            <button v-for="item in operations" :key="item.action" class="button" :class="{ danger: item.action === 'delete' }" type="button"
              :aria-expanded="actionExpanded(item.action, row.dataset)"
              :disabled="!row.images && requiresImages.has(item.action)" @click="runAction(item.action, row.dataset)">
              {{ actionLabel(item.action, item.label, row.dataset) }}
            </button>
          </div>
        </div>

        <div v-if="report?.datasetId === row.dataset.id" class="report-row" :role="view === 'list' ? 'row' : undefined">
          <DatasetQualityReport v-if="report.kind === 'quality'" :dataset="row.dataset" :report="report"
            :role="view === 'list' ? 'cell' : undefined" :aria-colspan="view === 'list' ? 6 : undefined"
            @close="emit('close-report')" @refresh="emit('refresh-report')" />
          <DatasetValidationReport v-else-if="report.kind === 'validate'" :report="report"
            :role="view === 'list' ? 'cell' : undefined" :aria-colspan="view === 'list' ? 6 : undefined"
            @close="emit('close-report')" @refresh="emit('refresh-report')" @open-image="emit('open-image', row.dataset, $event)" />
          <div v-else class="report" :role="view === 'list' ? 'cell' : undefined" :aria-colspan="view === 'list' ? 6 : undefined"
            :aria-busy="report.pending">
            <div class="report-heading">
              <strong>{{ report.title || '精确重复分析' }}</strong>
              <button class="text-button" type="button" @click="emit('close-report')">收起结果</button>
            </div>
            <DatasetReportState :report="report" @refresh="emit('refresh-report')" />
            <dl v-if="report.items?.length" class="report-metrics">
              <div v-for="item in report.items" :key="item.label">
                <dt>{{ item.label }}</dt><dd>{{ item.value }}</dd>
              </div>
            </dl>
            <template v-if="report.issues?.length">
              <p v-if="report.messages?.length" class="report-hint">{{ report.messages[0] }}</p>
              <div v-if="confirmedCount || reviewFilter === 'confirmed'" class="segmented review-filter" role="group" aria-label="重复图审核状态">
                <button type="button" :aria-pressed="reviewFilter === 'unconfirmed'" @click="reviewFilter = 'unconfirmed'">待处理与其他结果</button>
                <button type="button" :aria-pressed="reviewFilter === 'confirmed'" @click="reviewFilter = 'confirmed'">已确认重复（{{ formatNumber(confirmedCount) }}）</button>
              </div>
              <ul v-if="filteredIssues.length">
                <li v-for="(issue, index) in filteredIssues.slice(reportOffset, reportOffset + reportPageSize)" :key="reportOffset + index">
                  {{ issue.message }}
                  <button v-if="issue.image_id" type="button" class="text-button" @click="emit('open-image', row.dataset, issue.image_id)">查看图片</button>
                  <button v-if="issue.image_id && issue.related_image_id" type="button" class="text-button"
                    @click="emit('review-pair', row.dataset, issue, filteredIssues)">{{ canReview(issue) ? '人工审核' : '查看对比图' }}</button>
                </li>
              </ul>
              <p v-else class="report-hint">{{ reviewFilter === 'confirmed' ? '暂无已确认的重复图。' : '暂无待处理结果。' }}</p>
            </template>
            <ul v-else-if="report.messages?.length">
              <li v-for="(message, index) in report.messages.slice(reportOffset, reportOffset + reportPageSize)" :key="reportOffset + index">{{ message }}</li>
            </ul>
            <div v-if="reportMessageCount > reportPageSize" class="pagination-bar report-pagination">
              <span>共 {{ formatNumber(reportMessageCount) }} 条</span>
              <nav class="page-controls" aria-label="精确重复结果分页">
                <button class="button" type="button" :disabled="currentReportPage <= 1" @click="reportPage = currentReportPage - 1">上一页</button>
                <span aria-live="polite">{{ currentReportPage }} / {{ reportPageCount }} 页</span>
                <button class="button" type="button" :disabled="currentReportPage >= reportPageCount" @click="reportPage = currentReportPage + 1">下一页</button>
              </nav>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="pagination-bar">
      <span v-if="filtered.length">显示 {{ offset + 1 }}–{{ offset + visibleRows.length }} / 共 {{ filtered.length }} 个数据集</span>
      <span v-else>共 0 个数据集</span>
      <div class="page-controls" aria-label="数据集分页">
        <button class="button" type="button" aria-label="上一页" :disabled="currentPage <= 1" @click="page = currentPage - 1">‹</button>
        <span aria-current="page">{{ currentPage }}</span>
        <button class="button" type="button" aria-label="下一页" :disabled="currentPage >= pageCount" @click="page = currentPage + 1">›</button>
      </div>
    </div>

    <dl class="overview" aria-label="所有数据集统计">
      <div class="overview-cell">
        <dt>图片总数</dt>
        <dd>{{ formatNumber(totals.images) }} <small>张</small></dd>
      </div>
      <div class="overview-cell">
        <dt>总体标注完成率</dt>
        <dd>{{ totals.progress.toFixed(1) }}% <small>{{ formatNumber(totals.annotated) }} / {{ formatNumber(totals.images) }}</small></dd>
      </div>
      <div class="overview-cell type-overview">
        <dt>任务类型分布</dt>
        <dd class="overview-types">
          <span v-for="task in selectableDatasetTasks" :key="task">{{ taskShort[task] }} {{ totals.taskCounts[task] }}</span>
        </dd>
      </div>
      <div class="overview-cell">
        <dt>数据集总数</dt>
        <dd>{{ datasets.length }} <small>个</small></dd>
      </div>
    </dl>
  </section>
</template>

<style scoped>
.datasets-view {
  padding: 24px;
  min-width: 0;
  color: var(--text, #364152);
  --numeric: "JetBrains Mono", Consolas, monospace;
}
.datasets-heading, .heading-line, .heading-actions, .datasets-toolbar, .toolbar-right, .segmented,
.pagination-bar, .page-controls, .identity, .row-actions, .report-heading, .progress-caption, .name-line {
  display: flex;
  align-items: center;
}
.datasets-heading {
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--line, #e6e9ed);
}
.heading-line { gap: 10px; }
.heading-line h1 { margin: 0; font-size: 26px; line-height: 1.2; }
.index-label {
  padding: 2px 5px;
  border: 1px solid var(--line, #e6e9ed);
  border-radius: 2px;
  background: var(--soft, #f8f9fb);
  color: var(--muted, #5c6775);
  font: 10px/1.25 var(--numeric);
  white-space: nowrap;
}
.datasets-heading p { margin: 7px 0 0; color: var(--muted, #5c6775); font-size: 13px; }
.heading-actions, .toolbar-right { gap: 8px; }
.button svg, .view-toggle svg, .search-box svg, .task-icon svg {
  width: 16px; height: 16px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.7;
  stroke-linecap: round; stroke-linejoin: round;
}
.button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; white-space: nowrap; }
.datasets-toolbar { gap: 12px; flex-wrap: wrap; padding: 16px 0; }
.search-box {
  display: flex; align-items: center; gap: 8px; width: min(236px, 100%); min-height: 34px;
  border: 1px solid var(--line, #e6e9ed); padding: 0 9px; border-radius: 3px;
  background: var(--surface, #fff); color: var(--muted, #5c6775);
}
.search-box:focus-within { border-color: var(--primary, #4f6885); }
.search-box input {
  padding: 6px 0; min-width: 0; width: 100%; border: 0; outline: none; color: var(--text, #364152);
  font: inherit; font-size: 13px; background: transparent;
}
.toolbar-right { margin-left: auto; }
.segmented {
  gap: 2px; padding: 2px; border: 1px solid var(--line, #e6e9ed); border-radius: 3px;
  background: var(--soft, #f8f9fb);
}
.segmented button {
  display: flex; align-items: center; justify-content: center; gap: 5px; white-space: nowrap; padding: 6px 9px;
  background: transparent; border: 1px solid transparent; border-radius: 2px;
  color: var(--muted, #5c6775); font: inherit; font-size: 12px; cursor: pointer;
}
.segmented button[aria-pressed="true"] {
  background: var(--selected, #edf2f7); color: var(--primary, #4f6885); border-color: var(--line, #e6e9ed);
  font-weight: 600;
}
.view-toggle svg { width: 14px; height: 14px; }
.match-count {
  margin-left: 4px; color: var(--muted, #5c6775); font-size: 12px; white-space: nowrap;
}
.match-count::before {
  content: ""; display: inline-block; width: 6px; height: 6px; margin-right: 6px;
  border-radius: 50%; background: var(--primary, #4f6885); vertical-align: 2px;
}
.dataset-results { font-size: 13px; }
.list-view {
  --columns: minmax(166px, 1.55fr) minmax(86px, .8fr) minmax(60px, .42fr) minmax(54px, .39fr) minmax(120px, 1.05fr) 140px;
  border: 1px solid var(--line, #e6e9ed); border-radius: 7px; background: var(--surface, #fff);
}
.list-view .table-header, .list-view .dataset-row {
  display: grid; grid-template-columns: var(--columns); align-items: center;
  column-gap: 13px; padding: 10px 14px;
}
.table-header {
  border-radius: 6px 6px 0 0; background: var(--soft, #f8f9fb); color: var(--muted, #5c6775);
  font-size: 12px; min-height: 38px;
}
.num-heading, .list-view .numeric, .actions-heading { text-align: right; }
.list-view .dataset-entry { border-top: 1px solid var(--line, #e6e9ed); }
.list-view .dataset-row { min-height: 52px; }
.list-view .dataset-row:hover { background: var(--soft, #f8f9fb); }
.identity { min-width: 0; gap: 9px; }
.task-icon {
  width: 34px; height: 34px; flex: none; display: grid; place-items: center; border-radius: 4px;
  background: var(--selected, #edf2f7); color: var(--primary, #4f6885);
}
.task-icon svg { width: 19px; height: 19px; }
.identity-text { min-width: 0; }
.name-line { gap: 6px; }
.identity-text strong, .identity-text small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.identity-text strong { font-size: 13px; font-weight: 650; }
.identity-text small { display: block; color: var(--muted, #5c6775); font-size: 11px; margin-top: 2px; }
.task-cell { font-size: 12px; color: var(--muted, #5c6775); }
.numeric strong, .progress-numbers { font-family: var(--numeric); font-variant-numeric: tabular-nums; }
.numeric small, .muted, .metric-label { color: var(--muted, #5c6775); }
.numeric small, .metric-label, .progress-caption { font-size: 11px; }
.progress-cell { min-width: 0; }
.progress-caption { gap: 4px; justify-content: space-between; margin-bottom: 5px; }
.completed { color: #276340; }
progress {
  display: block; width: 100%; height: 5px; appearance: none; border: 0; border-radius: 4px;
  color: var(--primary, #4f6885); background: var(--selected, #edf2f7); overflow: hidden;
}
progress::-webkit-progress-bar { background: var(--selected, #edf2f7); }
progress::-webkit-progress-value { background: currentColor; }
progress::-moz-progress-bar { background: currentColor; }
progress.complete { color: #368150; }
.row-actions { gap: 6px; justify-content: flex-end; }
.main-action { font-size: 12px; min-height: 30px; }
.main-action svg { width: 14px; height: 14px; }
.more-button { font: 700 16px/1 system-ui; min-width: 30px; min-height: 30px; }
.menu-region { position: relative; }
.action-menu {
  position: absolute; z-index: 3; top: calc(100% + 4px); right: 0; min-width: 126px;
  padding: 4px; border: 1px solid var(--line, #e6e9ed); border-radius: 4px;
  background: var(--surface, #fff); box-shadow: 0 4px 12px #36415218;
}
.action-menu button, .text-button, .add-shortcut {
  color: var(--text, #364152); font: inherit; font-size: 12px; border: 0; background: none; cursor: pointer;
}
.action-menu button { display: block; width: 100%; text-align: left; padding: 6px 8px; border-radius: 2px; }
.action-menu button:hover:not(:disabled) { background: var(--soft, #f8f9fb); }
.action-menu button:disabled { opacity: .5; cursor: default; }
.action-menu .destructive { color: #a52727; }
.card-view { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); align-items: start; gap: 12px; }
.card-view .dataset-entry {
  min-width: 0; border: 1px solid var(--line, #e6e9ed); border-radius: 6px; background: var(--surface, #fff);
}
.card-view .dataset-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 13px; }
.card-view .identity, .card-view .progress-cell, .card-view .row-actions, .card-actions { grid-column: 1 / -1; }
.card-view .identity, .card-view .progress-cell {
  border-bottom: 1px solid var(--line, #e6e9ed); padding-bottom: 10px;
}
.card-view .identity { min-height: 42px; }
.add-shortcut { margin-left: auto; white-space: nowrap; padding: 4px 0 4px 3px; color: var(--primary, #4f6885); }
.card-view .numeric { padding: 10px 0; }
.card-view .numeric strong { font-size: 20px; }
.card-view .metric-label { display: block; margin-bottom: 2px; }
.card-view .progress-cell { border-top: 1px solid var(--line, #e6e9ed); padding-top: 9px; }
.card-view .row-actions { margin-top: 10px; }
.card-view .main-action { width: 100%; }
.card-actions { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 5px; margin-top: 8px; }
.card-actions .button { min-width: 0; min-height: 25px; padding: 3px 4px; font-size: 11px; }
.card-actions .button[aria-expanded="true"] { color: #fff; background: var(--primary, #4f6885); border-color: var(--primary, #4f6885); }
.card-actions .button[aria-expanded="true"]::before {
  content: ''; width: 5px; height: 5px; border-top: 1px solid; border-left: 1px solid; transform: translateY(1px) rotate(45deg);
}
.report-row { padding: 0 13px 13px; }
.report {
  padding: 9px 10px; border: 1px solid var(--line, #e6e9ed); border-radius: 5px;
  background: var(--soft, #f8f9fb); overflow-wrap: anywhere; font-size: 12px;
}
.report-heading { justify-content: space-between; gap: 5px; }
.text-button { white-space: nowrap; padding: 3px; color: var(--primary, #4f6885); }
.report-metrics { display: flex; flex-wrap: wrap; gap: 5px; margin: 6px 0 0; }
.report-metrics div { min-width: 56px; flex: 1; padding: 5px; background: var(--surface, #fff); }
.report-metrics dt { color: var(--muted, #5c6775); }
.report-metrics dd { margin: 1px 0 0; font-family: var(--numeric); font-weight: 600; }
.report-hint { margin: 7px 0 0; color: var(--muted, #5c6775); }
.review-filter { margin-top: 7px; width: fit-content; }
.report ul { padding-left: 16px; margin: 7px 0 0; }
.empty-state { text-align: center; padding: 42px 16px; border: 1px solid var(--line, #e6e9ed); }
.empty-state p { font-size: 13px; color: var(--muted, #5c6775); }
.pagination-bar {
  margin-top: 12px; padding: 6px 10px; justify-content: space-between;
  border: 1px solid var(--line, #e6e9ed); background: var(--soft, #f8f9fb);
  color: var(--muted, #5c6775); font-size: 12px;
}
.report-pagination { margin-top: 8px; padding: 5px 0 0; border-width: 1px 0 0; }
.page-controls { gap: 4px; font-family: var(--numeric); }
.page-controls button, .page-controls span {
  min-height: 25px; min-width: 25px; display: grid; place-items: center;
}
.page-controls span { border-radius: 2px; background: var(--selected, #edf2f7); color: var(--primary, #4f6885); }
.overview { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0 0; }
.overview-cell {
  min-width: 0; min-height: 72px; border: 1px solid var(--line, #e6e9ed); padding: 10px 12px;
  background: var(--soft, #f8f9fb); border-radius: 3px;
}
.overview-cell dt { color: var(--muted, #5c6775); font-size: 12px; }
.overview-cell dd { margin: 5px 0 0; font: 600 19px/1.3 var(--numeric); }
.overview-cell dd small { color: var(--muted, #5c6775); font-size: 10px; white-space: nowrap; }
.overview-cell .overview-types { display: flex; flex-wrap: wrap; gap: 4px; font-size: 11px; }
.overview-types span { background: var(--selected, #edf2f7); padding: 2px 4px; white-space: nowrap; }
@media (max-width: 1240px) {
  .card-view { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .list-view { --columns: minmax(125px, 1.35fr) minmax(60px, .55fr) 52px 46px minmax(92px, .9fr) 140px; }
  .list-view .table-header, .list-view .dataset-row { column-gap: 8px; padding-inline: 8px; }
}
@media (max-width: 880px) {
  .datasets-view { padding: 14px; }
  .list-view { overflow-x: auto; }
  .list-view .table-header, .list-view .dataset-entry { min-width: 620px; }
  .list-view:has(.action-menu) { padding-bottom: 250px; }
  .overview { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .card-view { grid-template-columns: 1fr; }
  .datasets-heading { align-items: flex-start; flex-direction: column; }
  .segmented.task-filter { flex-wrap: wrap; }
  .toolbar-right { margin-left: 0; }
}
</style>
