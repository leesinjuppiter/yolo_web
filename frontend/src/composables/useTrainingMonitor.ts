import { onScopeDispose, ref, shallowRef, watch } from 'vue'
import { refreshOnChanges } from '../api/changes'
import { cancelTraining, getTraining, getTrainingLogs, getTrainingMetrics, trainingPageLimit } from '../api/training'
import type { TrainingAction, TrainingLogEntry, TrainingMetricPoint, TrainingTask } from '../types/training'

const logWindow = 1000
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : '请求失败，请稍后重试'

export function useTrainingMonitor(taskId: () => string) {
  const task = shallowRef<TrainingTask>()
  const metrics = shallowRef<TrainingMetricPoint[]>([])
  const logs = shallowRef<TrainingLogEntry[]>([])
  const refreshing = ref(false)
  const refreshError = ref('')
  const action = ref<TrainingAction>()
  const actionError = ref('')
  let controller = new AbortController()
  let dirty = false
  let timer: ReturnType<typeof setTimeout> | undefined

  function stopRefresh() {
    clearTimeout(timer)
    controller.abort()
    controller = new AbortController()
    refreshing.value = false
  }

  async function refresh() {
    if (refreshing.value || action.value) { dirty = true; return }
    dirty = false
    clearTimeout(timer)
    const { signal } = controller
    const id = taskId()
    refreshing.value = true
    let pending = false
    try {
      const current = await getTraining(id, signal)
      if (signal.aborted) return
      task.value = current
      const [metricResult, logResult] = await Promise.allSettled([
        getTrainingMetrics(id, metrics.value.at(-1)?.sequence ?? 0, signal),
        getTrainingLogs(id, logs.value.at(-1)?.sequence ?? 0, signal),
      ])
      if (signal.aborted) return
      const failures: string[] = []
      if (metricResult.status === 'fulfilled') {
        const latest = metrics.value.at(-1)?.sequence ?? 0
        const added = metricResult.value.filter(point => point.sequence > latest).sort((a, b) => a.sequence - b.sequence)
        if (added.length) metrics.value = [...metrics.value, ...added]
        pending ||= metricResult.value.length >= trainingPageLimit
      } else failures.push(`曲线更新失败：${errorText(metricResult.reason)}`)
      if (logResult.status === 'fulfilled') {
        const latest = logs.value.at(-1)?.sequence ?? 0
        const added = logResult.value.filter(entry => entry.sequence > latest).sort((a, b) => a.sequence - b.sequence)
        if (added.length) logs.value = [...logs.value, ...added].slice(-logWindow)
        pending ||= logResult.value.length >= trainingPageLimit
      } else failures.push(`日志更新失败：${errorText(logResult.reason)}`)
      refreshError.value = failures.join('。')
    } catch (cause) {
      if (!signal.aborted) refreshError.value = errorText(cause)
    } finally {
      if (!signal.aborted) {
        refreshing.value = false
        if (pending || dirty) timer = setTimeout(refresh, 0)
      }
    }
  }

  async function runAction(nextAction: TrainingAction) {
    if (action.value || !task.value?.actions.includes(nextAction)) return
    stopRefresh()
    const { signal } = controller
    action.value = nextAction
    actionError.value = ''
    try {
      const result = await cancelTraining(taskId())
      if (!signal.aborted) task.value = result
    } catch (cause) {
      if (!signal.aborted) actionError.value = errorText(cause)
    } finally {
      if (!signal.aborted) {
        action.value = undefined
        void refresh()
      }
    }
  }

  watch(taskId, () => {
    stopRefresh()
    task.value = undefined
    metrics.value = []
    logs.value = []
    refreshError.value = ''
    action.value = undefined
    actionError.value = ''
    void refresh()
  }, { immediate: true })
  const unsubscribe = refreshOnChanges(['training', 'models'], refresh, change => change.topic === 'models' || change.id === taskId())
  onScopeDispose(() => { unsubscribe(); stopRefresh() })

  return { task, metrics, logs, refreshing, refreshError, action, actionError, refresh, runAction }
}
