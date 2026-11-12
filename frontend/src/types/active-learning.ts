import type { Annotation, AnnotationStatus, DatasetClass, DatasetImage } from '../domain'
import type { ModelVersion, JobLog } from './models'
import type { TrainingDevice } from './training'

export type ActiveTaskType = 'detect' | 'segment' | 'obb'
export type Strategy = 'error_first' | 'low_confidence' | 'mixed'
export interface Page<T> { items: T[]; total: number; page?: number; pageSize?: number }
export interface Counts { selected: number; reviewed: number; pending: number; new: number; revised: number; unchanged: number }
export interface Iteration {
  id: string; name: string; goal: string; datasetId: string; datasetName: string
  taskType: ActiveTaskType; baselineVersionId: string; sourceTaskId: string
  phase: string; createdAt: string; completedAt?: string; counts: Counts
  classes: DatasetClass[]; tasks?: RecommendationTask[]; trainingAttempts?: Attempt[]
  resultVersionId?: string; baselineEvaluationId?: string; resultEvaluationId?: string
}
export interface Attempt { id: string; name: string; status: string; modelVersionId?: string; manifestId?: string }
export interface RecommendationTask {
  id: string; iterationId: string; strategy: Strategy; status: string; phase: string
  processed: number; total: number; createdAt: string; error?: string; cancelRequested?: boolean
  config?: Record<string, unknown>
}
export interface Candidate {
  id: string; iterationId: string; taskId?: string; imageId: string; name: string
  purpose: 'training' | 'reference'; reasons: string[]; selected: boolean; reviewState: string
  confidence: number | null; thumbnailUrl?: string; image?: DatasetImage
  classes?: DatasetClass[]; predictions?: Annotation[]; referenceIds?: string[]; evidence?: Record<string, unknown>; unsupportedPrediction?: boolean
}
export interface ActiveOptions {
  models: ModelVersion[]; datasets: { id: string; name: string; task: ActiveTaskType }[]
  devices: TrainingDevice[]; evaluations: { id: string; versionId: string; status: string; purpose?: string }[]
}
export interface Overview { activeIterations: number; pendingReview: number; reviewed: number; pendingEvaluation: number }
export interface TaskConfig {
  iterationId: string; strategy: Strategy; evaluationId?: string; deviceId: string; imageSize: number
  minConfidence: number; maxConfidence: number; retainConfidence: number; nmsIou: number
  referenceLimit: number; candidateLimit: number; includeNoPredictions: boolean
}
export interface TrainingInput {
  iterationId: string; manifestId: string; manifestDigest: string; datasetId: string; modelId: string; task: ActiveTaskType
}
export interface Preflight {
  ready: boolean; checks: { code: string; label: string; passed: boolean; message?: string }[]
  issues: { message: string; imageId?: string; code?: string }[]
  counts: Record<string, number>; manifestId?: string; manifestDigest?: string
}
export interface Comparison {
  comparable: boolean; reasons: string[]
  rows: { key: string; label: string; baseline: number | null; result: number | null; delta: number | null }[]
}
export interface ReviewInput { version: number; annotations: Annotation[]; status: AnnotationStatus; negativeConfirmed: boolean }
export const strategyLabels: Record<Strategy, string> = { error_first: '评估错误优先', low_confidence: '低置信度', mixed: '混合推荐' }
export const phaseLabels: Record<string, string> = {
  active: '进行中',
  preparing: '样本准备', review: '人工复核', reviewing: '人工复核', ready: '待训练', ready_training: '待训练', ready_to_train: '待训练', awaiting_evaluation: '待评估',
  training: '训练中', evaluating: '待评估', ready_evaluation: '待评估', completed: '已完成',
  queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', canceled: '已取消',
  pending: '待复核', reviewed: '已复核', stale: '需重新复核', candidate: '候选',
}
export type ActiveLog = JobLog
