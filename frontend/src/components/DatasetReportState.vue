<script setup lang="ts">
import { computed } from 'vue'
import type { DatasetReport } from '../domain'

const props = defineProps<{ report: DatasetReport }>()
const emit = defineEmits<{ refresh: [] }>()
const date = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'medium' })
const number = new Intl.NumberFormat('zh-CN')
const generated = computed(() => {
  if (!props.report.generatedAt) return ''
  const value = new Date(props.report.generatedAt)
  return Number.isNaN(value.getTime()) ? '' : date.format(value)
})
const statusLabel = computed(() => ({
  loading: '正在读取…',
  idle: '尚未生成',
  queued: '等待后台处理',
  running: '后台处理中',
  ready: props.report.stale ? '等待更新' : '已更新',
  failed: '处理失败',
})[props.report.status])
const progress = computed(() => props.report.status === 'running' && props.report.progress?.total
  ? props.report.progress : undefined)
</script>

<template>
  <div class="report-state">
    <div class="report-state-line">
      <div class="report-state-meta" role="status">
        <span class="report-state-label" :class="report.status">{{ statusLabel }}</span>
        <span v-if="generated">上次生成 <time :datetime="report.generatedAt ?? undefined">{{ generated }}</time></span>
        <span v-if="generated && report.stale">当前显示上次结果</span>
      </div>
      <button class="report-refresh" type="button" :disabled="report.pending" @click="emit('refresh')">
        {{ report.status === 'failed' ? '重试' : report.kind === 'quality' ? '重新统计' : '重新扫描' }}
      </button>
    </div>
    <div v-if="progress" class="report-progress">
      <progress :value="progress.completed" :max="progress.total" aria-label="后台处理进度"></progress>
      <span>{{ number.format(progress.completed) }} / {{ number.format(progress.total) }}</span>
    </div>
    <p v-if="report.error" class="report-error" role="alert">{{ report.error }}</p>
  </div>
</template>

<style scoped>
.report-state { margin-top: 6px; font-size: 11px; color: var(--muted, #5c6775); }
.report-state-line, .report-state-meta, .report-progress { display: flex; align-items: center; gap: 6px; }
.report-state-line { justify-content: space-between; flex-wrap: wrap; }
.report-state-meta { flex-wrap: wrap; }
.report-state-label { font-weight: 600; }
.report-state-label.ready { color: #186432; }
.report-state-label.failed, .report-error { color: #a9292f; }
.report-refresh { padding: 2px 3px; border: 0; background: transparent; color: var(--primary, #4f6885); font: inherit; }
.report-refresh:hover:not(:disabled) { text-decoration: underline; }
.report-progress { margin-top: 5px; }
.report-progress progress { width: min(100%, 150px); height: 6px; accent-color: var(--primary, #4f6885); }
.report-error { margin: 5px 0 0; overflow-wrap: anywhere; }
</style>
