<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { TaskType } from '../../domain'
import type { TrainingMetricPoint } from '../../types/training'
import TrainingCurve from './TrainingCurve.vue'

type Group = 'overview' | 'losses' | 'metrics' | 'learning'
type Axis = 'epoch' | 'step' | 'elapsedSeconds'
type Chart = { title: string; series: { key: string; label: string }[] }

const props = defineProps<{ task: TaskType; points: TrainingMetricPoint[] }>()
const group = ref<Group>('overview')
const smoothing = ref(0)
const logarithmic = ref(false)
const axis = ref<Axis>('epoch')
const groups: { value: Group; label: string }[] = [
  { value: 'overview', label: '综合收敛' }, { value: 'losses', label: '损失函数' },
  { value: 'metrics', label: '评估指标' }, { value: 'learning', label: '学习率' },
]
const chart = (title: string, ...series: [key: string, label: string][]): Chart => ({
  title, series: series.map(([key, label]) => ({ key, label })),
})
const losses = computed(() => props.task === 'classify'
  ? [chart('分类损失', ['clsLoss', '训练'], ['valLoss', '验证'])]
  : [
      chart('定位损失', ['boxLoss', '训练'], ['valBoxLoss', '验证']),
      chart('分类损失', ['clsLoss', '训练'], ['valClsLoss', '验证']),
      chart('DFL 损失', ['dflLoss', '训练'], ['valDflLoss', '验证']),
      ...(props.task === 'segment' ? [chart('掩膜损失', ['segLoss', '训练'], ['valSegLoss', '验证'])] : []),
    ])
const metrics = computed(() => props.task === 'classify'
  ? [chart('分类准确率', ['top1', 'Top-1'], ['top5', 'Top-5'])]
  : [
      chart('定位精度 mAP', ['map50', 'mAP@50'], ['map50_95', 'mAP@50–95']),
      chart('精确率与召回率', ['precision', 'Precision'], ['recall', 'Recall']),
      ...(props.task === 'segment' ? [chart('掩膜精度 mAP', ['maskMap50', 'Mask mAP@50'], ['maskMap50_95', 'Mask mAP@50–95'])] : []),
    ])
const options = computed(() => ({
  overview: [...losses.value.slice(0, 2), ...metrics.value],
  losses: losses.value,
  metrics: metrics.value,
  learning: [chart('学习率调度', ['learningRate', 'Learning rate'])],
}))
const canUseStep = computed(() => props.points.some(point => Number.isFinite(point.step)))
const canUseTime = computed(() => props.points.some(point => Number.isFinite(point.elapsedSeconds)))
watch([canUseStep, canUseTime], ([step, time]) => {
  if ((axis.value === 'step' && !step) || (axis.value === 'elapsedSeconds' && !time)) axis.value = 'epoch'
})
</script>

<template>
  <section class="charts" aria-labelledby="training-charts-title">
    <header>
      <h2 id="training-charts-title">训练收敛曲线</h2>
      <span class="sample-count">{{ points.length }} 个采样轮次</span>
    </header>
    <div class="chart-toolbar">
      <div class="chart-tabs" role="group" aria-label="曲线分组">
        <button v-for="item in groups" :key="item.value" type="button" class="button"
          :aria-pressed="group === item.value" @click="group = item.value">{{ item.label }}</button>
      </div>
      <label>平滑 <input v-model.number="smoothing" type="range" min="0" max=".95" step=".05"> <output>{{ smoothing.toFixed(2) }}</output></label>
      <label>X 轴
        <select v-model="axis">
          <option value="epoch">Epoch</option>
          <option value="step" :disabled="!canUseStep">Step</option>
          <option value="elapsedSeconds" :disabled="!canUseTime">耗时</option>
        </select>
      </label>
      <label><input v-model="logarithmic" type="checkbox"> 对数坐标</label>
    </div>
    <div v-if="points.length" class="chart-grid">
      <TrainingCurve v-for="item in options[group]" :key="item.title" v-bind="item"
        :points="points" :axis="axis" :smoothing="smoothing" :logarithmic="logarithmic"/>
    </div>
    <p v-else class="empty-chart">完成首个训练轮次后，这里会显示曲线。</p>
  </section>
</template>

<style scoped>
.charts { min-width: 0; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; }
header, .chart-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; padding: 11px 14px; }
header { justify-content: space-between; border-bottom: 1px solid var(--line); }
h2 { font-size: 14px; margin: 0; }
.sample-count, .chart-toolbar label { font-size: 12px; color: var(--muted); }
.chart-toolbar { background: var(--soft); border-bottom: 1px solid var(--line); }
.chart-tabs { display: flex; flex-wrap: wrap; gap: 4px; }
.chart-tabs .button { min-height: 26px; font-size: 12px; padding: 4px 8px; border-color: transparent; background: transparent; }
.chart-tabs .button[aria-pressed="true"] { background: var(--selected); color: #214eaa; border-color: #ccdaed; }
.chart-toolbar label { display: inline-flex; align-items: center; gap: 5px; }
input[type="range"] { width: 70px; margin: 0; accent-color: var(--primary); }
select { border: 1px solid var(--line); border-radius: 4px; padding: 2px 4px; background: var(--surface); }
.chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: 9px; padding: 11px; }
.empty-chart { min-height: 190px; display: grid; place-items: center; margin: 0; padding: 15px; color: var(--muted); text-align: center; }
</style>
