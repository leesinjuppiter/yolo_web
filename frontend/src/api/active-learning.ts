import type { ActiveOptions, Candidate, Comparison, Iteration, Overview, Page, Preflight, RecommendationTask, ReviewInput, TaskConfig, ActiveLog } from '../types/active-learning'
const root = '/api/active-learning'
const at = (kind: string, id: string) => `${root}/${kind}/${encodeURIComponent(id)}`
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...init })
  if (!response.ok) {
    const value = await response.json().catch(() => null)
    const detail = value?.detail
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map(item => `${item.loc?.slice(1).join('.') ?? ''}：${item.msg}`).join('；') : detail?.message
    throw new Error(message || `主动学习请求失败（HTTP ${response.status}）`)
  }
  return response.json() as Promise<T>
}
const post = (value: unknown, key?: string): RequestInit => ({ method: 'POST', body: JSON.stringify(value),
  headers: { 'Content-Type': 'application/json', ...(key ? { 'Idempotency-Key': key } : {}) } })
function query(params: URLSearchParams) {
  const values = new URLSearchParams(params)
  for (const [key,value] of [...values]) if (!value) values.delete(key)
  return values
}
const list = <T>(kind: string, params: URLSearchParams, signal?: AbortSignal) => request<Page<T>>(`${root}/${kind}?${query(params)}`, { signal })
export async function activeOptions(): Promise<ActiveOptions> {
  const result = await request<Omit<ActiveOptions,'evaluations'> & {evaluations:{id:string;versionId:string;config:{purpose?:string}}[]}>(`${root}/options`)
  return {...result,evaluations:result.evaluations.map(item=>({...item,status:'succeeded',purpose:item.config.purpose}))}
}
export async function activeOverview(signal?: AbortSignal): Promise<Overview> {
  const result = await request<{activeIterations:number;pending:number;reviewed:number;awaitingEvaluation:number}>(`${root}/overview`,{signal})
  return {...result,pendingReview:result.pending,pendingEvaluation:result.awaitingEvaluation}
}
export const listIterations = (params: URLSearchParams, signal?: AbortSignal) => list<Iteration>('iterations', params, signal)
export const getIteration = (id: string, signal?: AbortSignal) => request<Iteration>(at('iterations', id), { signal })
export const createIteration = (value: { name: string; goal: string; baselineVersionId: string; datasetId: string }) => request<Iteration>(`${root}/iterations`, post(value))
export const listActiveTasks = (params: URLSearchParams, signal?: AbortSignal) => list<RecommendationTask>('tasks', params, signal)
export const getActiveTask = (id: string, signal?: AbortSignal) => request<RecommendationTask>(at('tasks', id), { signal })
export const createActiveTask = (value: TaskConfig, key: string) => request<RecommendationTask>(`${root}/tasks`, post(value, key))
export const cancelActiveTask = (id: string) => request<RecommendationTask>(`${at('tasks', id)}/cancel`, post({}))
export const activeLogs = (id: string) => request<{ items: ActiveLog[] }>(`${at('tasks', id)}/logs`)
export const listCandidates = (taskId: string, params: URLSearchParams, signal?: AbortSignal) => request<Page<Candidate>>(`${at('tasks', taskId)}/candidates?${query(params)}`, { signal })
export const candidateDetail = (id: string) => request<Candidate>(at('candidates', id))
export const selectCandidates = (id: string, candidateIds: string[], selected: boolean) => request(`${at('iterations', id)}/selection`, post({ candidateIds, selected }))
export const addCandidates = (id: string, imageIds: string[]) => request<{added:number;candidateIds:string[]}>(`${at('iterations', id)}/candidates`, post({ imageIds, reason: 'manual_revision' }))
export const linkReferences = (id: string, referenceIds: string[]) => request(`${at('candidates', id)}/references`, post({ referenceIds }))
export const reviewQueue = (id: string, params: URLSearchParams, signal?: AbortSignal) => request<Page<Candidate>>(`${at('iterations', id)}/review-queue?${params}`, { signal })
export const confirmReview = (id: string, value: ReviewInput) => request<Candidate>(`${at('candidates', id)}/review`, post(value))
export const prepareActiveTraining = (id: string) => request<Preflight>(`${at('iterations',id)}/prepare-training`,post({}))
export const activeComparison = (id: string) => request<Comparison>(`${at('iterations',id)}/comparison`)
export const chooseActiveResult = (id: string, value: { versionId: string; baselineEvaluationId: string; resultEvaluationId: string }) => request(`${at('iterations', id)}/result`, post(value))
export const completeIteration = (id: string) => request(`${at('iterations', id)}/complete`, post({}))
export const createValDiagnostic = (versionId: string, sourceTaskId: string, imgsz: number, key: string) =>
  request<{id:string}>('/api/evaluations',post({versionId,sourceTaskId,imgsz,purpose:'diagnostic',deviceId:'cpu'},key))
