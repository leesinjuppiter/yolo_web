<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { TrainingLogEntry } from '../../types/training'

const props = defineProps<{ entries: TrainingLogEntry[]; downloadName: string; downloadUrl?: string; active?: boolean }>()
const levels = {
  all: 'ALL', info: 'INFO', warn: 'WARNING', error: 'ERROR', metric: 'METRICS',
} satisfies Record<'all' | TrainingLogEntry['level'], string>
const level = ref<keyof typeof levels>('all')
const search = ref('')
const follow = ref(true)
const feedback = ref('')
const logViewport = ref<HTMLElement>()
const root = ref<HTMLElement>()
const query = computed(() => search.value.trim().toLowerCase())
const visible = computed(() => props.entries.filter(entry =>
  (level.value === 'all' || entry.level === level.value)
  && (!query.value || entry.message.toLowerCase().includes(query.value)),
))
const counts = computed(() => {
  let errors = 0
  let warnings = 0
  for (const entry of props.entries) {
    if (entry.level === 'error') errors++
    if (entry.level === 'warn') warnings++
  }
  return { errors, warnings }
})
const asText = computed(() => visible.value.map(entry => `[${entry.time}] [${levels[entry.level]}] ${entry.message}`).join('\n'))
const time = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : time.format(date)
}

watch([() => visible.value.at(-1)?.sequence, level, query, follow, () => props.active], async () => {
  await nextTick()
  const viewport = logViewport.value
  if (follow.value && viewport?.clientHeight) viewport.scrollTop = viewport.scrollHeight
}, { immediate: true })

function onScroll() {
  const viewport = logViewport.value
  if (viewport?.clientHeight && viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight > 24) follow.value = false
}

async function copyLog() {
  try {
    await navigator.clipboard.writeText(asText.value)
    feedback.value = '已复制当前日志'
  } catch {
    feedback.value = '复制失败，可下载当前日志'
  }
}

function downloadLog() {
  const url = URL.createObjectURL(new Blob([asText.value], { type: 'text/plain;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.downloadName}-logs.txt`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

function focus() {
  root.value?.focus({ preventScroll: true })
  root.value?.scrollIntoView({ block: 'start' })
}

defineExpose({ focus })
</script>

<template>
  <section ref="root" class="training-logs" tabindex="-1" aria-labelledby="training-logs-title">
    <header class="log-header">
      <h2 id="training-logs-title">实时训练日志</h2>
      <div class="log-toolbar">
        <input v-model="search" class="log-search" type="search" aria-label="搜索日志内容" placeholder="搜索日志内容…">
        <label>级别
          <select v-model="level">
            <option v-for="(label, value) in levels" :key="value" :value="value">{{ label }}</option>
          </select>
        </label>
        <label><input v-model="follow" type="checkbox"> 自动滚动</label>
        <button type="button" class="button" :disabled="!visible.length" @click="copyLog">复制</button>
        <button type="button" class="button" :disabled="!visible.length" @click="downloadLog">下载当前日志</button>
        <a v-if="downloadUrl" class="button" :href="downloadUrl" download>下载完整日志</a>
      </div>
    </header>
    <p v-if="feedback" class="feedback" role="status">{{ feedback }}</p>
    <div ref="logViewport" class="log-viewport" tabindex="0" role="region" aria-label="日志内容" @scroll="onScroll">
      <p v-if="!visible.length" class="empty-log">{{ entries.length ? '没有符合筛选条件的日志' : '暂无训练日志' }}</p>
      <ol v-else>
        <li v-for="entry in visible" :key="entry.sequence" :class="`log-${entry.level}`">
          <time :datetime="entry.time">{{ formatTime(entry.time) }}</time>
          <span class="log-level">{{ levels[entry.level] }}</span>
          <span class="log-message">{{ entry.message }}</span>
        </li>
      </ol>
    </div>
    <footer class="log-footer">
      <span>已加载 {{ entries.length }} 条</span>
      <span>当前显示 {{ visible.length }} 条</span>
      <span class="warning-count">WARNING {{ counts.warnings }}</span>
      <span class="error-count">ERROR {{ counts.errors }}</span>
    </footer>
  </section>
</template>

<style scoped>
.training-logs { min-width: 0; scroll-margin-top: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: 6px; }
.log-header { display: flex; flex-wrap: wrap; align-items: center; gap: 7px 12px; padding: 10px 14px; border-bottom: 1px solid var(--line); background: var(--soft); border-radius: 6px 6px 0 0; }
h2 { margin: 0; font-size: 14px; }
.log-footer, .feedback { color: var(--muted); font-size: 12px; }
.feedback { margin: 0; padding: 5px 14px; border-bottom: 1px solid var(--line); }
.log-toolbar { display: flex; flex: 1 1 580px; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 7px; }
.log-toolbar label { display: flex; align-items: center; gap: 5px; font-size: 12px; }
select, .log-search { min-height: 30px; padding: 4px 8px; border: 1px solid var(--line); border-radius: 4px; background: var(--surface); color: inherit; font-size: 12px; }
.log-search { width: min(210px, 100%); }
input { margin: 0; accent-color: var(--primary); }
.log-toolbar .button { display: inline-flex; align-items: center; min-height: 30px; padding: 4px 8px; font-size: 12px; text-decoration: none; }
.log-viewport {
  height: clamp(280px, 55vh, 640px); overflow: auto; padding: 6px 10px;
  background: #0b0b0b; color: #e2e8f0; color-scheme: dark;
}
.log-viewport:focus-visible { outline: 2px solid #93c5fd; outline-offset: -2px; }
ol { list-style: none; margin: 0; padding: 0; font: 12px/1.6 Consolas, "Microsoft YaHei UI", monospace; }
li {
  display: grid; grid-template-columns: 8ch 9ch minmax(0, 1fr); align-items: baseline; gap: 9px;
  padding: 4px 8px; border-inline-start: 2px solid transparent;
}
time { color: #a2aab6; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.log-level { justify-self: start; border-radius: 3px; padding: 0 4px; font-weight: 700; }
.log-message { overflow-wrap: anywhere; white-space: pre-wrap; }
.log-info .log-level { color: #93c5fd; background: #152334; }
.log-warn { color: #facc15; background: #241d0d; border-inline-start-color: #e2a510; }
.log-warn .log-level { background: #3a2b10; }
.log-error { color: #fca5a5; background: #281518; border-inline-start-color: #ce3140; }
.log-error .log-level { background: #421b20; }
.log-metric .log-level { color: #6ee7b7; background: #10281e; }
.empty-log { margin: 12px 8px; color: #a2aab6; font-size: 12px; }
.log-footer { display: flex; flex-wrap: wrap; gap: 5px 16px; padding: 8px 14px; border-top: 1px solid var(--line); font-variant-numeric: tabular-nums; }
.warning-count { color: #6b4b00; }
.error-count { color: #9d1c2b; }
@media (max-width: 640px) { .log-toolbar { justify-content: flex-start; } }
</style>
