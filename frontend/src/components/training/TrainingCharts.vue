<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { TaskType } from '../../domain'
import type { TrainingMetricPoint } from '../../types/training'
import TrainingCurve from './TrainingCurve.vue'

type Group = 'overview' | 'losses' | 'metrics' | 'learning'
type Axis = 'epoch' | 'step' | 'elapsedSeconds'
type Chart = { title: string; series: { key: string; label: string; colorIndex: number }[] }

const props = defineProps<{ task: TaskType; points: TrainingMetricPoint[] }>()
const group = ref<Group>('overview')
const query = ref('')
const smoothing = ref(0)
const logarithmic = ref(false)
const axis = ref<Axis>('epoch')
const groups: { value: Group; label: string }[] = [
  { value: 'overview', label: '全部指标' }, { value: 'losses', label: '损失函数' },
  { value: 'metrics', label: '评估指标' }, { value: 'learning', label: '学习率' },
]
const axes: { value: Axis; label: string }[] = [
  { value: 'epoch', label: 'Epoch' }, { value: 'step', label: 'Step' }, { value: 'elapsedSeconds', label: 'Time' },
]
const chart = (title: string, ...series: [key: string, label: string][]): Chart => ({
  title, series: series.map(([key, label], colorIndex) => ({ key, label, colorIndex })),
})
const losses = computed(() => props.task === 'classify'
  ? [chart('分类损失', ['clsLoss', '训练分类损失'], ['valLoss', '验证分类损失'])]
  : [
      chart('训练与验证损失对比',
        ['boxLoss', '训练定位损失'], ['valBoxLoss', '验证定位损失'],
        ['clsLoss', '训练分类损失'], ['valClsLoss', '验证分类损失']),
      chart('DFL 损失', ['dflLoss', '训练 DFL'], ['valDflLoss', '验证 DFL']),
      ...(props.task === 'segment' ? [chart('掩膜损失', ['segLoss', '训练掩膜损失'], ['valSegLoss', '验证掩膜损失'])] : []),
    ])
const metrics = computed(() => props.task === 'classify'
  ? [chart('分类准确率', ['top1', 'Top-1'], ['top5', 'Top-5'])]
  : [
      chart('定位精度 mAP', ['map50', 'mAP@50'], ['map50_95', 'mAP@50–95']),
      chart('精确率与召回率', ['precision', 'Precision'], ['recall', 'Recall']),
      ...(props.task === 'segment' ? [chart('掩膜精度 mAP', ['maskMap50', 'Mask mAP@50'], ['maskMap50_95', 'Mask mAP@50–95'])] : []),
    ])
const learning = [chart('学习率调度', ['learningRate', 'Learning rate'])]
const options = computed(() => {
  const [mainLoss, ...otherLosses] = losses.value
  return {
    overview: [mainLoss!, ...metrics.value.slice(0, 2), ...learning, ...otherLosses, ...metrics.value.slice(2)],
    losses: losses.value,
    metrics: metrics.value,
    learning,
  }
})
const normalize = (value: string) => value.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '')
const visibleCharts = computed(() => {
  const filter = normalize(query.value)
  return options.value[group.value].flatMap(item => {
    if (!filter || normalize(item.title).includes(filter)) return [item]
    const series = item.series.filter(({ key, label }) => {
      const trainingKey = key.endsWith('Loss') && !key.startsWith('val') ? `train${key}` : key
      return normalize(trainingKey).includes(filter) || normalize(label).includes(filter)
    })
    return series.length ? [{ ...item, series }] : []
  })
})
const selectedKeys = computed(() => [...new Set(visibleCharts.value.flatMap(item => item.series.map(series => series.key)))])
const canUseAxis = computed(() => ({
  epoch: true,
  step: props.points.some(point => Number.isFinite(point.step)),
  elapsedSeconds: props.points.some(point => Number.isFinite(point.elapsedSeconds)),
}))
watch(canUseAxis, (available) => {
  if (!available[axis.value]) axis.value = 'epoch'
})

function exportValue(point: TrainingMetricPoint, key: string) {
  const value = point.values[key]
  return value !== undefined && Number.isFinite(value) && (!logarithmic.value || value > 0) ? value : ''
}

const canExport = computed(() => props.points.some(point =>
  Number.isFinite(point[axis.value]) && selectedKeys.value.some(key => exportValue(point, key) !== '')))

function reset() {
  group.value = 'overview'
  query.value = ''
  smoothing.value = 0
  logarithmic.value = false
  axis.value = 'epoch'
}

function exportCsv() {
  const keys = selectedKeys.value
  const rows = props.points.flatMap(point => {
    if (!Number.isFinite(point[axis.value])) return []
    const values = keys.map(key => exportValue(point, key))
    if (!values.some(value => value !== '')) return []
    return [[point.epoch, point.step, point.elapsedSeconds, ...values].join(',')]
  })
  if (!rows.length) return
  const header = ['epoch', 'step', 'elapsed_seconds', ...keys].join(',')
  const url = URL.createObjectURL(new Blob([[header, ...rows].join('\r\n')], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'training-metrics.csv'
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}
</script>

<template>
  <section class="charts" aria-labelledby="training-charts-title">
    <header>
      <h2 id="training-charts-title">指标曲线</h2>
      <span class="sample-count">{{ points.length }} 个采样轮次 · {{ selectedKeys.length }} 条已选曲线</span>
    </header>
    <div class="chart-toolbar">
      <div class="chart-tabs" role="group" aria-label="曲线分组">
        <button v-for="item in groups" :key="item.value" type="button" class="button"
          :aria-pressed="group === item.value" @click="group = item.value">{{ item.label }}</button>
      </div>
      <input v-model="query" class="curve-filter" type="search" aria-label="筛选曲线" placeholder="筛选曲线（如 box_loss）">
    </div>
    <div class="chart-toolbar chart-controls">
      <label>平滑 <input v-model.number="smoothing" type="range" min="0" max=".95" step=".05"> <output>{{ smoothing.toFixed(2) }}</output></label>
      <div class="axis-controls" role="group" aria-label="X 轴">
        <span>X 轴</span>
        <div class="chart-tabs">
          <button v-for="item in axes" :key="item.value" type="button" class="button"
            :disabled="!canUseAxis[item.value]" :aria-pressed="axis === item.value" @click="axis = item.value">{{ item.label }}</button>
        </div>
      </div>
      <label><input v-model="logarithmic" type="checkbox"> 对数坐标</label>
      <button type="button" class="button" @click="reset">重置</button>
      <button type="button" class="button export-button" :disabled="!canExport" @click="exportCsv">导出数据 CSV</button>
    </div>
    <p v-if="!points.length" class="empty-chart">完成首个训练轮次后，这里会显示曲线。</p>
    <p v-else-if="!visibleCharts.length" class="empty-chart">没有符合筛选条件的曲线。</p>
    <div v-else class="chart-grid">
      <TrainingCurve v-for="item in visibleCharts" :key="item.title" v-bind="item"
        :points="points" :axis="axis" :smoothing="smoothing" :logarithmic="logarithmic"/>
    </div>
  </section>
</template>

<style scoped>
.charts { min-width: 0; background: var(--surface); border: 1px solid var(--line); border-radius: 6px; }
header, .chart-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; padding: 10px 12px; }
header { justify-content: space-between; border-bottom: 1px solid var(--line); }
h2 { font-size: 15px; margin: 0; }
.sample-count, .chart-toolbar { font-size: 12px; color: var(--muted); }
.chart-toolbar { justify-content: space-between; background: var(--soft); border-bottom: 1px solid var(--line); }
.chart-controls { justify-content: flex-start; }
.chart-tabs { display: flex; flex-wrap: wrap; gap: 4px; }
.chart-toolbar .button { min-height: 27px; padding: 4px 9px; font-size: 12px; }
.chart-tabs .button[aria-pressed="true"] { background: var(--primary); border-color: var(--primary); color: white; }
.chart-toolbar label, .axis-controls { display: inline-flex; align-items: center; gap: 6px; }
.axis-controls, output { font-variant-numeric: tabular-nums; }
.chart-controls input { margin: 0; accent-color: var(--primary); }
input[type="range"] { width: 86px; }
.curve-filter { width: min(100%, 215px); min-height: 28px; border: 1px solid #c7d1de; border-radius: 4px; padding: 4px 8px; background: var(--surface); }
.export-button { background: var(--selected); }
.chart-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 12px; background: var(--soft); }
.charts { container-type: inline-size; }
@container (max-width: 680px) { .chart-grid { grid-template-columns: minmax(0, 1fr); } }
.empty-chart { min-height: 190px; display: grid; place-items: center; margin: 0; padding: 15px; color: var(--muted); text-align: center; }
</style>
