<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { TrainingLogEntry } from '../../types/training'

const props = defineProps<{ entries: TrainingLogEntry[]; downloadName: string }>()
const levels = [
  { value: 'all', label: '全部' }, { value: 'info', label: '信息' }, { value: 'warn', label: '警告' },
  { value: 'error', label: '错误' }, { value: 'metric', label: '指标' },
] as const
const level = ref<(typeof levels)[number]['value']>('all')
const follow = ref(true)
const expanded = ref(true)
const feedback = ref('')
const logViewport = ref<HTMLElement>()
const root = ref<HTMLElement>()
const visible = computed(() => level.value === 'all' ? props.entries : props.entries.filter(entry => entry.level === level.value))
const asText = computed(() => visible.value.map(entry => `[${entry.time}] [${entry.level.toUpperCase()}] ${entry.message}`).join('\n'))
const time = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : time.format(date)
}

watch([() => visible.value.at(-1)?.sequence, level, follow, expanded], async () => {
  await nextTick()
  const viewport = logViewport.value
  if (follow.value && viewport) viewport.scrollTop = viewport.scrollHeight
}, { immediate: true })

function onScroll() {
  const viewport = logViewport.value
  if (viewport && viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight > 24) follow.value = false
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
    <header>
      <h2 id="training-logs-title">实时训练日志</h2>
      <span class="entry-count">{{ visible.length }} / {{ entries.length }} 条已加载</span>
      <div class="log-toolbar">
        <label>级别
          <select v-model="level">
            <option v-for="option in levels" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <label><input v-model="follow" type="checkbox"> 自动滚动</label>
        <button type="button" class="button" :disabled="!visible.length" @click="copyLog">复制</button>
        <button type="button" class="button" :disabled="!visible.length" @click="downloadLog">下载当前日志</button>
        <button type="button" class="button" :aria-expanded="expanded" aria-controls="training-log-viewport"
          @click="expanded = !expanded">{{ expanded ? '收起' : '展开' }}</button>
      </div>
    </header>
    <p v-if="feedback" class="feedback" role="status">{{ feedback }}</p>
    <div v-show="expanded" id="training-log-viewport" ref="logViewport" class="log-viewport" tabindex="0" aria-label="日志内容" @scroll="onScroll">
      <p v-if="!visible.length" class="empty-log">{{ entries.length ? '当前级别暂无日志' : '等待训练日志' }}</p>
      <ol v-else>
        <li v-for="entry in visible" :key="entry.sequence" :class="`log-${entry.level}`">
          <time :datetime="entry.time">{{ formatTime(entry.time) }}</time>
          <span class="log-level">{{ entry.level.toUpperCase() }}</span>
          <span class="log-message">{{ entry.message }}</span>
        </li>
      </ol>
    </div>
  </section>
</template>

<style scoped>
.training-logs { min-width: 0; scroll-margin-top: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; }
header { display: flex; flex-wrap: wrap; align-items: center; gap: 7px 12px; padding: 10px 14px; border-bottom: 1px solid var(--line); background: var(--soft); border-radius: 10px 10px 0 0; }
h2 { margin: 0; font-size: 14px; }
.entry-count, .feedback { color: var(--muted); font-size: 12px; }
.feedback { margin: 0; padding: 5px 14px; border-bottom: 1px solid var(--line); }
.log-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-left: auto; }
.log-toolbar label { display: flex; align-items: center; gap: 5px; font-size: 12px; }
select { padding: 4px 6px; border: 1px solid var(--line); border-radius: 4px; background: var(--surface); }
input { margin: 0; accent-color: var(--primary); }
.log-toolbar .button { min-height: 27px; padding: 4px 8px; font-size: 12px; }
.log-viewport { min-height: 114px; max-height: 270px; overflow: auto; padding: 8px 14px; }
ol { list-style: none; margin: 0; padding: 0; font: 12px/1.55 Consolas, "Microsoft YaHei UI", monospace; }
li { display: grid; grid-template-columns: auto 48px minmax(0, 1fr); align-items: baseline; gap: 7px; padding: 3px 0; border-bottom: 1px solid var(--soft); }
time { color: var(--muted); font-variant-numeric: tabular-nums; }
.log-level { font-weight: 600; }
.log-message { overflow-wrap: anywhere; white-space: pre-wrap; }
.log-warn .log-level { color: #935b17; }
.log-error .log-level { color: var(--danger); }
.log-metric .log-level { color: #137564; }
.empty-log { color: var(--muted); font-size: 12px; }
@media (max-width: 640px) { .log-toolbar { margin-left: 0; } }
</style>
