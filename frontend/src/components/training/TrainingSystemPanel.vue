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
const hostMemoryPercent = computed(() => {
  const current = sample.value
  return current?.hostMemoryTotalBytes && current.hostMemoryUsedBytes != null
    ? current.hostMemoryUsedBytes / current.hostMemoryTotalBytes * 100 : undefined
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
    <div class="resource-cards">
      <article><h3>主机 CPU 使用率</h3><strong>{{ percent(sample?.hostCpuPercent) }}</strong>
        <progress v-if="sample?.hostCpuPercent != null" :value="sample.hostCpuPercent" max="100" aria-label="主机 CPU 使用率"/></article>
      <article><h3>主机内存</h3><strong>{{ memory(sample?.hostMemoryUsedBytes) }}</strong><span> / {{ memory(sample?.hostMemoryTotalBytes) }}</span>
        <progress v-if="hostMemoryPercent != null" :value="hostMemoryPercent" max="100" aria-label="主机内存使用率"/></article>
      <article><h3>训练进程 CPU 使用率</h3><strong>{{ percent(sample?.processCpuPercent) }}</strong></article>
      <article><h3>训练进程常驻内存</h3><strong>{{ memory(sample?.processMemoryBytes) }}</strong></article>
    </div>
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
.system-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 10px; }
.topology { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 12px; }
.topology div { display: grid; flex: 1 1 95px; gap: 3px; padding: 9px; border: 1px solid #d7e1ed; background: #f2f6fc; font-size: 12px; }
.sample-table { overflow: auto; max-height: 236px; margin-top: 8px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; text-align: left; }
th, td { padding: 6px; border-bottom: 1px solid var(--line); white-space: nowrap; }
th { background: var(--soft); }
.resource-notice { margin-top: 6px; }
</style>
