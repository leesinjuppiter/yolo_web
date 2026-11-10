<script setup lang="ts">
import { computed } from 'vue'
import type { Dataset, DatasetReport } from '../domain'
import DatasetReportState from './DatasetReportState.vue'

const props = defineProps<{ dataset: Dataset; report: DatasetReport }>()
const emit = defineEmits<{ close: []; refresh: [] }>()
const formatNumber = new Intl.NumberFormat('zh-CN')
const formatShare = new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 1, minimumFractionDigits: 1 })
const coverageLabel = '已检查覆盖率'
const metrics = computed(() => props.report.items ?? [])
const annotatedCount = computed(() => Number(metrics.value.find(item => item.label === '已标注')?.value ?? 0))
const totalCount = computed(() => Number(metrics.value.find(item => item.label === '标注总数')?.value ?? 0))
const coverage = computed(() => {
  const value = Number.parseFloat(String(metrics.value.find(item => item.label === coverageLabel)?.value ?? ''))
  return Number.isFinite(value) ? value : undefined
})
const metricDetails = computed<Record<string, { unit?: string; note?: string; tone?: string }>>(() => ({
  已标注: { unit: '张', note: '含有效标注', tone: 'positive' },
  负样本: { unit: '张', note: '已确认无目标', tone: 'neutral' },
  未标注: { unit: '张', note: '待标注', tone: 'warning' },
  标注总数: {
    unit: ['detect', 'obb'].includes(props.dataset.task) ? '框' : '个',
    note: annotatedCount.value ? `平均 ${(totalCount.value / annotatedCount.value).toFixed(1)} / 图` : undefined,
  },
}))

const classBreakdown = computed(() => {
  const total = totalCount.value
  return props.dataset.classes.map(entry => {
    const count = props.report.class_counts?.[entry.id] ?? 0
    return { ...entry, count, share: total ? count / total : 0 }
  }).sort((a, b) => b.count - a.count)
})
</script>

<template>
  <section class="quality-panel" aria-label="数据质量报告" :aria-busy="report.pending">
    <header class="quality-heading">
      <div class="quality-heading-main">
        <strong>{{ report.title || '数据质量报告' }}</strong>
        <span v-if="metrics.length && report.status === 'ready' && !report.stale" class="quality-status">分析完成</span>
      </div>
      <button class="quality-collapse" type="button" @click="emit('close')">
        收起结果
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path d="m4 10 4-4 4 4"/>
        </svg>
      </button>
    </header>
    <DatasetReportState :report="report" @refresh="emit('refresh')" />

    <template v-if="metrics.length">
      <dl class="quality-metrics">
        <div v-for="metric in metrics" :key="metric.label" class="quality-metric" :class="metricDetails[metric.label]?.tone">
          <dt>{{ metric.label }}</dt>
          <dd>
            <strong>{{ typeof metric.value === 'number' ? formatNumber.format(metric.value) : metric.value }}</strong>
            <small v-if="metricDetails[metric.label]?.unit">{{ metricDetails[metric.label]?.unit }}</small>
          </dd>
          <progress v-if="metric.label === coverageLabel && coverage !== undefined"
            class="quality-progress" :class="{ complete: coverage >= 100 }" :value="coverage" max="100" aria-label="已检查覆盖率"></progress>
          <small v-else-if="metricDetails[metric.label]?.note" class="metric-note">{{ metricDetails[metric.label]?.note }}</small>
        </div>
      </dl>

      <section class="quality-breakdown" aria-label="类别分布明细">
        <div class="breakdown-heading">
          <strong>类别分布明细</strong>
          <span>共 {{ formatNumber.format(classBreakdown.length) }} 个类别</span>
        </div>
        <ul v-if="classBreakdown.length" class="quality-classes">
          <li v-for="entry in classBreakdown" :key="entry.id" class="quality-class" :style="{ '--class-color': entry.color }">
            <span class="class-dot" aria-hidden="true"></span>
            <strong :title="entry.name">{{ entry.name }}</strong>
            <span class="class-count">{{ formatNumber.format(entry.count) }} 个</span>
            <span class="class-share">{{ formatShare.format(entry.share) }}</span>
          </li>
        </ul>
        <p v-else class="quality-empty">暂无类别</p>
      </section>
    </template>
    <ul v-else-if="report.messages?.length" class="quality-errors">
      <li v-for="(message, index) in report.messages" :key="index">{{ message }}</li>
    </ul>
  </section>
</template>

<style scoped>
.quality-panel {
  padding: 12px; border: 1px solid #dce4ee; border-radius: 8px;
  background: #f6f8fa; color: #243142; font-size: 12px;
  container-type: inline-size;
}
.quality-heading, .quality-heading-main, .breakdown-heading {
  display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
}
.quality-heading, .breakdown-heading { justify-content: space-between; }
.quality-heading-main > strong { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.quality-heading-main > strong::before, .quality-status::before, .class-dot {
  content: ''; display: inline-block; width: 7px; height: 7px; border-radius: 50%; flex: none;
}
.quality-heading-main > strong::before { background: var(--primary, #4f6885); }
.quality-status {
  display: inline-flex; align-items: center; gap: 4px; padding: 2px 6px; border-radius: 12px;
  border: 1px solid #a9e7cd; color: #146348; background: #ecfdf5; font-size: 10px;
}
.quality-status::before { width: 5px; height: 5px; background: #159a70; }
.quality-collapse {
  display: inline-flex; align-items: center; gap: 3px; padding: 3px; border: 0;
  background: transparent; color: var(--muted, #5c6775); font: inherit; white-space: nowrap; cursor: pointer;
}
.quality-collapse:hover { color: var(--primary, #4f6885); }
.quality-metrics {
  display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px; margin: 10px 0 0;
}
.quality-metric { min-width: 0; padding: 7px 5px; border: 1px solid #dce4ee; border-radius: 5px; background: #fff; }
.quality-metric dt, .quality-metric dd small, .metric-note, .breakdown-heading span, .quality-empty {
  font-size: 10px; color: var(--muted, #5c6775);
}
.quality-metric dt, .quality-metric dd { overflow-wrap: anywhere; }
.quality-metric dd { display: flex; flex-wrap: wrap; align-items: baseline; column-gap: 3px; margin: 3px 0 0; }
.quality-metric dd strong { font: 700 clamp(12px, 4cqw, 15px)/1.2 var(--numeric, monospace); }
.quality-metric.positive dd strong { color: #245ed0; }
.quality-metric.neutral dd strong { color: #5d6c81; }
.quality-metric.warning dd strong, .quality-metric.warning .metric-note { color: #9a5008; }
.metric-note { display: block; margin-top: 3px; }
.quality-progress {
  display: block; width: 100%; height: 4px; margin-top: 5px; border: 0; border-radius: 4px;
  overflow: hidden; appearance: none; background: #e9eef3; color: #d98b12;
}
.quality-progress.complete { color: #28805a; }
.quality-progress::-webkit-progress-bar { background: #e9eef3; }
.quality-progress::-webkit-progress-value { background: currentColor; border-radius: 4px; }
.quality-progress::-moz-progress-bar { background: currentColor; border-radius: 4px; }
.quality-breakdown { margin-top: 11px; padding-top: 8px; border-top: 1px solid #dce4ee; }
.breakdown-heading strong { font-size: 11px; font-weight: 600; }
.quality-classes { display: flex; flex-wrap: wrap; gap: 5px; list-style: none; margin: 7px 0 0; padding: 0; }
.quality-class {
  display: inline-flex; align-items: center; gap: 5px; max-width: 100%; min-width: 0;
  padding: 3px 6px; border: 1px solid #dce4ee; border-radius: 3px; background: #fff; font: 11px/1.3 var(--numeric, monospace);
}
.quality-class strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.class-dot { background: var(--class-color); }
.class-count { color: var(--muted, #5c6775); white-space: nowrap; }
.class-share {
  padding: 1px 3px; border: 1px solid color-mix(in srgb, var(--class-color) 20%, #fff);
  border-radius: 2px; color: color-mix(in srgb, var(--class-color) 52%, #17243a);
  background: color-mix(in srgb, var(--class-color) 10%, #fff); white-space: nowrap;
}
.quality-empty, .quality-errors { margin: 7px 0 0; }
.quality-errors { padding-left: 18px; overflow-wrap: anywhere; }
@container (width < 309px) {
  .quality-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
</style>
