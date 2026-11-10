<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TrainingMetricPoint } from '../../types/training'

type Axis = 'epoch' | 'step' | 'elapsedSeconds'
const props = defineProps<{
  title: string
  series: { key: string; label: string }[]
  points: TrainingMetricPoint[]
  axis: Axis
  smoothing: number
  logarithmic: boolean
}>()

const palette = ['#315d91', '#18826d', '#9a6343', '#7358a5']
const plot = { left: 58, right: 408, top: 13, bottom: 145 }
const activeX = ref<number>()
const number = new Intl.NumberFormat('zh-CN', { maximumSignificantDigits: 4 })
const axisTitle: Record<Axis, string> = { epoch: 'Epoch', step: 'Step', elapsedSeconds: '耗时（秒）' }
const traces = computed(() => props.series.map((series, index) => {
  let previous: number | undefined
  const samples = props.points.flatMap(point => {
    const x = point[props.axis]
    const raw = point.values[series.key]
    if (x === undefined || !Number.isFinite(x) || !Number.isFinite(raw) || (props.logarithmic && raw <= 0)) return []
    const smoothed: number = previous === undefined ? raw : props.smoothing * previous + (1 - props.smoothing) * raw
    previous = smoothed
    return [{ x, raw, y: props.logarithmic ? Math.log10(smoothed) : smoothed }]
  })
  return { ...series, color: palette[index % palette.length], samples }
}).filter(trace => trace.samples.length))

const domain = computed(() => {
  const first = traces.value[0]?.samples[0]
  if (!first) return { minX: 0, maxX: 1, minY: 0, maxY: 1 }
  let minX = first.x
  let maxX = first.x
  let minY = first.y
  let maxY = first.y
  for (const { samples } of traces.value) {
    for (const point of samples) {
      minX = Math.min(minX, point.x)
      maxX = Math.max(maxX, point.x)
      minY = Math.min(minY, point.y)
      maxY = Math.max(maxY, point.y)
    }
  }
  const padding = maxY === minY ? Math.abs(maxY) * .08 || .1 : (maxY - minY) * .08
  return { minX, maxX, minY: minY - padding, maxY: maxY + padding }
})

const xPosition = (x: number) => {
  const { minX, maxX } = domain.value
  return minX === maxX ? (plot.left + plot.right) / 2 : plot.left + (x - minX) / (maxX - minX) * (plot.right - plot.left)
}
const yPosition = (y: number) => plot.bottom - (y - domain.value.minY) / (domain.value.maxY - domain.value.minY) * (plot.bottom - plot.top)
const paths = computed(() => traces.value.map(trace => ({
  ...trace,
  coordinates: trace.samples.map(point => `${xPosition(point.x)},${yPosition(point.y)}`).join(' '),
})))
const xValues = computed(() => [...new Set(traces.value.flatMap(trace => trace.samples.map(point => point.x)))].sort((a, b) => a - b))
const selectedX = computed(() => {
  const target = activeX.value
  if (target === undefined || !xValues.value.length) return xValues.value.at(-1)
  return xValues.value.reduce((closest, x) => Math.abs(x - target) < Math.abs(closest - target) ? x : closest)
})
const selectedPoints = computed(() => traces.value.map(trace => ({
  ...trace,
  point: trace.samples.find(point => point.x === selectedX.value),
})))
const xTicks = computed(() => {
  const values = xValues.value
  return values.length <= 3 ? values : [values[0], values[Math.floor(values.length / 2)], values.at(-1)!]
})
const yTicks = computed(() => [0, 1, 2, 3].map(index => domain.value.minY + (domain.value.maxY - domain.value.minY) * index / 3))

function selectAt(event: PointerEvent) {
  const svg = event.currentTarget as SVGSVGElement
  const matrix = svg.getScreenCTM()
  if (!matrix) return
  const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
  const fraction = Math.max(0, Math.min(1, (point.x - plot.left) / (plot.right - plot.left)))
  activeX.value = domain.value.minX + fraction * (domain.value.maxX - domain.value.minX)
}

function moveSelection(offset: number) {
  if (selectedX.value === undefined) return
  const index = xValues.value.indexOf(selectedX.value) + offset
  activeX.value = xValues.value[Math.max(0, Math.min(xValues.value.length - 1, index))]
}
</script>

<template>
  <article class="curve">
    <h3>{{ title }}</h3>
    <div v-if="traces.length" class="curve-content">
      <svg viewBox="0 0 420 173" :aria-label="`${title}曲线，使用左右方向键查看采样点`" tabindex="0"
        @pointermove="selectAt" @pointerleave="activeX = undefined" @blur="activeX = undefined"
        @keydown.left.prevent="moveSelection(-1)" @keydown.right.prevent="moveSelection(1)">
        <g v-for="tick in yTicks" :key="tick">
          <line :x1="plot.left" :x2="plot.right" :y1="yPosition(tick)" :y2="yPosition(tick)" class="curve-grid"/>
          <text :x="plot.left - 7" :y="yPosition(tick) + 4" text-anchor="end">{{ number.format(logarithmic ? 10 ** tick : tick) }}</text>
        </g>
        <line :x1="plot.left" :x2="plot.right" :y1="plot.bottom" :y2="plot.bottom" class="curve-axis"/>
        <text v-for="tick in xTicks" :key="tick" :x="xPosition(tick)" y="164" text-anchor="middle">{{ number.format(tick) }}</text>
        <line v-if="selectedX !== undefined" :x1="xPosition(selectedX)" :x2="xPosition(selectedX)"
          :y1="plot.top" :y2="plot.bottom" class="curve-selection"/>
        <polyline v-for="trace in paths" :key="trace.key" :stroke="trace.color" :points="trace.coordinates"
          fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
        <template v-for="trace in selectedPoints" :key="trace.key">
          <circle v-if="trace.point" :cx="xPosition(trace.point.x)" :cy="yPosition(trace.point.y)" r="3.5" :fill="trace.color"/>
        </template>
      </svg>
      <div class="curve-legend">
        <strong>{{ axisTitle[axis] }} {{ selectedX === undefined ? '—' : number.format(selectedX) }}</strong>
        <span v-for="trace in selectedPoints" :key="trace.key">
          <i :style="{ background: trace.color }"></i>
          {{ trace.label }} {{ trace.point ? number.format(trace.point.raw) : '—' }}
        </span>
      </div>
    </div>
    <p v-else class="empty-curve">{{ logarithmic ? '对数坐标需要正值数据' : '等待采样数据' }}</p>
  </article>
</template>

<style scoped>
.curve { min-width: 0; border: 1px solid var(--line); border-radius: 7px; background: var(--surface); padding: 11px 12px; }
h3 { margin: 0 0 6px; font-size: 13px; }
svg { display: block; width: 100%; min-height: 142px; touch-action: pan-y; }
text { font: 10px ui-monospace, monospace; fill: var(--muted); }
.curve-grid { stroke: var(--line); stroke-dasharray: 3 3; }
.curve-axis { stroke: #bac7d6; }
.curve-selection { stroke: #a1b0c3; stroke-dasharray: 4 3; }
.curve-legend { min-height: 18px; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 12px; font-size: 11px; color: var(--muted); }
.curve-legend strong { color: var(--text); font-variant-numeric: tabular-nums; }
.curve-legend span { white-space: nowrap; }
.curve-legend i { display: inline-block; width: 8px; height: 8px; margin-right: 2px; border-radius: 50%; }
.empty-curve { display: grid; min-height: 155px; place-items: center; color: var(--muted); font-size: 12px; margin: 0; }
</style>
