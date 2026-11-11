<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { getTrainingResources } from '../../api/training'
import { terminalTrainingStates, trainingStatusLabels } from '../../types/training'
import type { TrainingResources, TrainingTask } from '../../types/training'

const props = defineProps<{ task: TrainingTask; active: boolean }>()
const resources = shallowRef<TrainingResources>()
const error = shallowRef('')
const history = shallowRef<NonNullable<TrainingResources['sample']>[]>([])
const sample = computed(() => resources.value?.sample)
const memoryLabel = computed(() => sample.value?.memoryScope === 'container' ? '实例内存' : '宿主机内存')
const gpu = computed(() => sample.value?.gpu)
const usesGpu = computed(() => props.task.config.deviceId.startsWith('cuda:'))
const live = computed(() => resources.value?.state === 'live' && !error.value)
const statusText = {
  waiting: '等待训练进程', live: '实时采样', stale: '采样已过期',
  unavailable: '资源采样不可用', finished: '训练已结束',
}
const time = new Intl.DateTimeFormat('zh-CN', { timeStyle: 'medium' })
const percent = (value?: number) => value == null ? '—' : `${value.toFixed(1)}%`
const memory = (value?: number) => value == null ? '—'
  : value >= 1024 ** 3 ? `${(value / 1024 ** 3).toFixed(2)} GiB` : `${(value / 1024 ** 2).toFixed(1)} MiB`
const percentValue = (value?: number) => value == null ? '—' : value.toFixed(1)
const memoryValue = (value?: number) => value == null ? '—'
  : value >= 1024 ** 3 ? (value / 1024 ** 3).toFixed(2) : (value / 1024 ** 2).toFixed(1)
const memoryUnit = (value?: number) => value == null ? '' : value >= 1024 ** 3 ? 'GiB' : 'MiB'
const hostMemoryPercent = computed(() => {
  const current = sample.value
  return current?.hostMemoryTotalBytes && current.hostMemoryUsedBytes != null
    ? current.hostMemoryUsedBytes / current.hostMemoryTotalBytes * 100 : undefined
})
const remainingMemory = computed(() => {
  const current = sample.value
  return current?.hostMemoryTotalBytes != null && current.hostMemoryUsedBytes != null
    ? Math.max(0, current.hostMemoryTotalBytes - current.hostMemoryUsedBytes) : undefined
})

watch([() => props.active, () => props.task.id, () => terminalTrainingStates.has(props.task.status)],
  ([active, id, finished], _, onCleanup) => {
    if (!active) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    async function refresh() {
      try {
        const result = await getTrainingResources(id, controller.signal)
        if (controller.signal.aborted) return
        resources.value = result
        error.value = ''
        if (result.sample && result.sample.sampledAt !== history.value.at(-1)?.sampledAt) {
          history.value = [...history.value, result.sample].slice(-12)
        }
      } catch (cause) {
        if (!controller.signal.aborted) error.value = cause instanceof Error ? cause.message : '资源采样读取失败'
      } finally {
        if (!controller.signal.aborted && !finished && resources.value?.state !== 'finished') {
          timer = setTimeout(refresh, 5000)
        }
      }
    }
    onCleanup(() => { controller.abort(); clearTimeout(timer) })
    void refresh()
  }, { immediate: true })
</script>

<template>
  <section class="system-panel" aria-labelledby="training-system-title">
    <header class="system-header">
      <div><h2 id="training-system-title">执行资源监控</h2><p>{{ task.device?.name ?? task.config.deviceId }} · 单任务运行</p></div>
      <div class="sample-state" :data-live="live">
        {{ error ? '刷新失败' : resources ? statusText[resources.state] : '正在读取采样' }}
        <time v-if="sample" :datetime="sample.sampledAt">{{ live ? '' : '最后采样 ' }}{{ time.format(new Date(sample.sampledAt)) }}</time>
      </div>
    </header>
    <p v-if="error" class="resource-notice" role="alert">{{ error }}</p>
    <p v-if="usesGpu && !gpu" class="resource-notice">当前没有可用的 GPU 采样，未采集到的数值显示为未知。</p>
    <div v-if="usesGpu" class="resource-cards">
      <article><h3>整卡 GPU 使用率</h3><strong>{{ percent(gpu?.utilizationPercent) }}</strong>
        <progress v-if="gpu?.utilizationPercent != null" :value="gpu.utilizationPercent" max="100" aria-label="整卡 GPU 使用率"/></article>
      <article><h3>整卡显存</h3><strong>{{ memory(gpu?.memoryUsedBytes) }}</strong><span> / {{ memory(gpu?.memoryTotalBytes) }}</span></article>
      <article><h3>训练进程显存</h3><strong>{{ memory(gpu?.processMemoryBytes) }}</strong><span>仅本次训练进程</span></article>
    </div>
    <div class="resource-cards host-resource-cards">
      <article>
        <header class="resource-heading">
          <h3><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 9h6v6H9zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg>主机 CPU 使用率</h3>
          <span class="resource-tag">整机</span>
        </header>
        <div class="resource-body">
          <div class="resource-value"><strong>{{ percentValue(sample?.hostCpuPercent) }}</strong><span v-if="sample?.hostCpuPercent != null">%</span></div>
          <progress v-if="sample?.hostCpuPercent != null" :value="sample.hostCpuPercent" max="100" aria-label="主机 CPU 使用率"/>
          <p class="metric-description">主机整体 CPU 平均使用率</p>
        </div>
        <footer class="resource-footer"><span>采样时间</span><time v-if="sample" :datetime="sample.sampledAt">{{ time.format(new Date(sample.sampledAt)) }}</time><span v-else>—</span></footer>
      </article>
      <article>
        <header class="resource-heading">
          <h3><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5h18v5H3zM3 14h18v5H3zM6 7.5h.01M6 16.5h.01M10 7.5h8M10 16.5h8"/></svg>{{ memoryLabel }}</h3>
          <span class="resource-tag">{{ percent(hostMemoryPercent) }} 已用</span>
        </header>
        <div class="resource-body">
          <div class="resource-value"><strong>{{ memoryValue(sample?.hostMemoryUsedBytes) }}</strong><span>{{ memoryUnit(sample?.hostMemoryUsedBytes) }}</span></div>
          <p class="capacity-total">/ {{ memory(sample?.hostMemoryTotalBytes) }} {{ sample?.memoryScope === 'container' ? '上限' : '总量' }}</p>
          <progress v-if="hostMemoryPercent != null" :value="hostMemoryPercent" max="100" :aria-label="`${memoryLabel}使用率`"/>
          <div class="resource-detail"><span>未占用{{ sample?.memoryScope === 'container' ? '额度' : '量' }}</span><b>{{ memory(remainingMemory) }}</b></div>
        </div>
        <footer class="resource-footer">{{ sample?.memoryScope === 'container' ? '容器总占用（含文件缓存）' : '宿主机口径，非当前实例配额' }}</footer>
      </article>
      <article class="process-cpu-card">
        <header class="resource-heading">
          <h3 aria-label="训练进程 CPU 使用率"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-13-2 16"/></svg>训练进程 CPU</h3>
          <span class="resource-tag">整机折算</span>
        </header>
        <div class="resource-body">
          <div class="resource-value"><strong>{{ percentValue(sample?.processCpuPercent) }}</strong><span v-if="sample?.processCpuPercent != null">%</span></div>
          <progress v-if="sample?.processCpuPercent != null" :value="sample.processCpuPercent" max="100" aria-label="训练进程 CPU 使用率"/>
          <p class="metric-description">训练主进程使用率，按主机逻辑 CPU 数折算</p>
        </div>
        <footer class="resource-footer"><span>统计范围</span><b>仅训练主进程</b></footer>
      </article>
      <article>
        <header class="resource-heading">
          <h3><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10h16v10H4zM8 10V6a4 4 0 0 1 8 0v4M8 14v3M12 14v3M16 14v3"/></svg>训练进程常驻内存</h3>
          <span class="resource-tag">RSS</span>
        </header>
        <div class="resource-body">
          <div class="resource-value"><strong>{{ memoryValue(sample?.processMemoryBytes) }}</strong><span>{{ memoryUnit(sample?.processMemoryBytes) }}</span></div>
          <p class="metric-description">训练主进程常驻物理内存</p>
          <div class="resource-detail"><span>数据来源</span><b>{{ live ? '实时采样' : sample ? '最后一次采样' : '等待采样' }}</b></div>
        </div>
        <footer class="resource-footer"><span>统计范围</span><b>仅训练主进程</b></footer>
      </article>
    </div>
    <p v-if="sample?.hostMemoryTotalBytes != null && !sample.memoryScope" class="resource-notice">该任务保留历史采样，记录的是宿主机内存；新训练任务将记录实例内存。</p>
    <div class="system-grid">
      <article class="system-box">
        <h3>执行关系</h3>
        <div class="topology">
          <div><strong>{{ task.device?.name ?? task.config.deviceId }}</strong><small>计算设备</small></div><span aria-hidden="true">→</span>
          <div><strong>训练 Worker</strong><small>任务调度与采集</small></div><span aria-hidden="true">→</span>
          <div><strong>训练进程</strong><small>{{ live && sample?.processId ? `PID ${sample.processId}` : trainingStatusLabels[task.status] }}</small></div>
        </div>
      </article>
      <article class="system-box">
        <h3>最近资源采样</h3>
        <div v-if="history.length" class="sample-table">
          <table>
            <thead><tr><th>采样时间</th><th>主机 CPU</th><th>训练 CPU</th><th>训练内存</th><th v-if="usesGpu">整卡 GPU</th><th v-if="usesGpu">训练显存</th></tr></thead>
            <tbody><tr v-for="item in [...history].reverse()" :key="item.sampledAt">
              <td>{{ time.format(new Date(item.sampledAt)) }}</td><td>{{ percent(item.hostCpuPercent) }}</td>
              <td>{{ percent(item.processCpuPercent) }}</td><td>{{ memory(item.processMemoryBytes) }}</td>
              <td v-if="usesGpu">{{ percent(item.gpu?.utilizationPercent) }}</td><td v-if="usesGpu">{{ memory(item.gpu?.processMemoryBytes) }}</td>
            </tr></tbody>
          </table>
        </div>
        <p v-else class="resource-notice">{{ resources?.state === 'finished' ? '该任务没有资源采样记录。' : '收到资源采样后将在这里显示。' }}</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.system-panel { display: grid; gap: 12px; min-width: 0; }
.system-header, .resource-cards article, .system-box { padding: 14px; background: var(--surface); border: 1px solid var(--line); border-radius: 5px; min-width: 0; }
.system-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; }
h2, h3, p { margin: 0; }
h2 { font-size: 16px; } h3 { font-size: 13px; }
.system-header p, .resource-notice, small, .resource-cards span { color: var(--muted); font-size: 12px; }
.sample-state { padding: 4px 9px; border-radius: 4px; background: var(--soft); color: var(--muted); font-size: 12px; }
.sample-state[data-live="true"] { background: #e6f4ed; color: #20644c; }
time { margin-left: 6px; font: 12px Consolas, monospace; }
.resource-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr)); gap: 10px; }
.resource-cards strong { display: inline-block; margin-top: 8px; font: 700 24px Consolas, monospace; }
progress { display: block; width: 100%; height: 7px; margin-top: 10px; accent-color: var(--primary); }
.host-resource-cards { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.host-resource-cards article { display: flex; flex-direction: column; padding: 0; min-height: 225px; border-color: #cbd2dc; border-radius: 3px; box-shadow: 0 1px 3px #36415208; }
.resource-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px; min-height: 48px; padding: 11px 0; margin: 0 12px; border-bottom: 1px solid #dce5f4; }
.resource-heading h3 { display: flex; align-items: center; gap: 7px; font-size: 12px; }
.resource-heading svg { width: 16px; height: 16px; flex-shrink: 0; fill: none; stroke: #4f6885; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.resource-heading .resource-tag { color: #657385; background: #f1f4fa; border-radius: 2px; padding: 2px 5px; font: 10px/1.4 Consolas, 'Microsoft YaHei UI', monospace; }
.resource-body { display: grid; align-content: start; gap: 10px; min-width: 0; padding: 14px 12px; }
.resource-value { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; min-width: 0; }
.host-resource-cards .resource-value strong { min-width: 0; margin: 0; font: 700 clamp(27px, 2.1vw, 35px)/1.2 Consolas, monospace; overflow-wrap: anywhere; color: #182334; }
.resource-value span { font: 12px Consolas, monospace; }
.process-cpu-card .resource-value strong { color: #37506c; }
.resource-body progress { margin: 2px 0 0; height: 6px; border: 0; border-radius: 2px; overflow: hidden; appearance: none; background: #e6edfa; color: #4f6885; }
.resource-body progress::-webkit-progress-bar { background: #e6edfa; }
.resource-body progress::-webkit-progress-value { background: currentColor; border-radius: 2px; }
.resource-body progress::-moz-progress-bar { background: currentColor; border-radius: 2px; }
.resource-body .metric-description { color: var(--muted); font-size: 11px; line-height: 1.6; }
.capacity-total { margin-top: -5px; color: var(--muted); font: 11px/1.5 Consolas, 'Microsoft YaHei UI', monospace; }
.resource-detail { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 5px; }
.resource-detail span { font-size: 10px; }
.resource-detail b, .resource-footer b { font-weight: 500; color: #4f6885; font-size: 11px; }
.resource-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 5px; margin-top: auto; padding: 9px 12px; border-top: 1px solid #dce5f4; color: var(--muted); background: #fafbfe; font-size: 10px; line-height: 1.5; }
.resource-footer span, .resource-footer time { margin: 0; font-size: 10px; }
@media (max-width: 1120px) { .host-resource-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) { .host-resource-cards { grid-template-columns: minmax(0, 1fr); } }
.system-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 10px; }
.topology { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 12px; }
.topology div { display: grid; flex: 1 1 95px; gap: 3px; padding: 9px; border: 1px solid #d7e1ed; background: #f2f6fc; font-size: 12px; }
.sample-table { overflow: auto; max-height: 236px; margin-top: 8px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; text-align: left; }
th, td { padding: 6px; border-bottom: 1px solid var(--line); white-space: nowrap; }
th { background: var(--soft); }
.resource-notice { margin-top: 6px; }
</style>
