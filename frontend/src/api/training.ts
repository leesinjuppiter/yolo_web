import type { Dataset } from '../domain'
import type {
  TrainingConfig, TrainingFilters, TrainingLogEntry, TrainingMetricPoint,
  TrainingOptions, TrainingOverview, TrainingPreflight, TrainingResources, TrainingTask,
} from '../types/training'

const root = '/api/training'
const at = (id: string) => `${root}/${encodeURIComponent(id)}`
export const trainingPageLimit = 200

export class DuplicateTrainingNameError extends Error {}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, { cache: 'no-store', ...init })
  } catch (error) {
    if (init?.signal?.aborted) throw error
    throw new Error('无法连接训练服务，请确认后端已启动。')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    if (response.status === 409 && detail === '训练任务名称已存在，请使用其他名称') {
      throw new DuplicateTrainingNameError(detail)
    }
    const reason = typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map(item => item.msg).join('；') : detail?.message
    throw new Error(reason || `训练请求失败（HTTP ${response.status}）`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const post = (value: unknown, key?: string): RequestInit => ({
  method: 'POST', body: JSON.stringify(value),
  headers: { 'Content-Type': 'application/json', ...(key ? { 'Idempotency-Key': key } : {}) },
})

export function trainingDatasetError(dataset: Dataset) {
  if (!dataset.classes.length) return '数据集尚未定义类别。'
  const exported = dataset.images.filter(image =>
    image.status === 'annotated' || (dataset.task !== 'classify' && image.status === 'negative'))
  if (exported.some(image => !image.split)) return '有可用样本尚未分集，请先调整分集。'
  const annotatedSplits = new Set(exported.filter(image => image.status === 'annotated').map(image => image.split))
  if (!annotatedSplits.has('train') || !annotatedSplits.has('val')) return '训练集和验证集均至少需要一张已标注图片。'
  return ''
}

export const getTrainingOptions = (signal?: AbortSignal) => request<TrainingOptions>(`${root}/options`, { signal })

export function listTraining(filters: TrainingFilters, signal?: AbortSignal) {
  const params = new URLSearchParams({
    page: String(filters.page), page_size: String(filters.pageSize), sort: filters.sort,
  })
  if (filters.status !== 'all') params.set('status', filters.status)
  if (filters.task !== 'all') params.set('task', filters.task)
  if (filters.architecture !== 'all') params.set('architecture', filters.architecture)
  if (filters.query.trim()) params.set('query', filters.query.trim())
  return request<TrainingOverview>(`${root}?${params}`, { signal })
}

export const checkTraining = (config: TrainingConfig) => request<TrainingPreflight>(`${root}/preflight`, post(config))
export const createTraining = (config: TrainingConfig, key: string) => request<TrainingTask>(root, post(config, key))
export const getTraining = (id: string, signal?: AbortSignal) => request<TrainingTask>(at(id), { signal })
export const getTrainingResources = (id: string, signal?: AbortSignal) =>
  request<TrainingResources>(`${at(id)}/resources`, { signal })
export const trainingLogDownloadUrl = (id: string) => `${at(id)}/logs/download`
export const cancelTraining = (id: string) => request<TrainingTask>(`${at(id)}/cancel`, post({}))
export const deleteTraining = (id: string) => request<void>(at(id), { method: 'DELETE' })
export const registerTrainingModel = (id: string) => request<TrainingTask['modelVersion']>(`${at(id)}/model-version`, post({}))

export function getTrainingMetrics(id: string, after: number, signal?: AbortSignal) {
  return request<TrainingMetricPoint[]>(`${at(id)}/metrics?after_sequence=${after}&limit=${trainingPageLimit}`, { signal })
}

export function getTrainingLogs(id: string, after: number, signal?: AbortSignal) {
  return request<TrainingLogEntry[]>(`${at(id)}/logs?after_sequence=${after}&limit=${trainingPageLimit}`, { signal })
}
