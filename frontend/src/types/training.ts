import type { SelectableDatasetTask } from '../domain'

export type TrainingStatus = 'created' | 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'
export type TrainingAction = 'cancel'

export const trainingStatusLabels: Record<TrainingStatus, string> = {
  created: '已创建',
  queued: '排队中',
  running: '训练中',
  succeeded: '已完成',
  failed: '失败',
  canceled: '已取消',
}

export const terminalTrainingStates = new Set<TrainingStatus>(['succeeded', 'failed', 'canceled'])

export const trainingPhaseLabels: Record<string, string> = {
  created: '等待准备', validating: '校验数据', preparing: '生成训练快照', queued: '等待执行资源',
  starting: '启动训练进程', training: '训练模型', validating_model: '验证模型',
  checking: '校验数据', snapshot: '生成训练快照', loading: '加载模型',
  validation: '验证模型', archiving: '归档产物', finished: '已结束',
}

export interface TrainingConfig {
  name: string
  datasetId: string
  task: SelectableDatasetTask
  modelId: string
  deviceId: string
  epochs: number
  batchSize: number
  imageSize: number
  optimizer: string
  learningRate: number
  finalLearningRate: number
  seed: number
  patience: number
  amp: boolean
  freeze?: number
  workers?: number
  augmentation: string
}

export interface TrainingModel {
  id: string
  name: string
  architecture: string
  task: SelectableDatasetTask
  pretrained: boolean
  sourceType?: 'architecture' | 'local_weights' | 'official_weights' | 'model_version'
  sourceUrl?: string | null
  pretrainingDataset?: string | null
  versionId?: string
  sourceTaskId?: string
}

export interface TrainingDevice {
  id: string
  name: string
  kind: 'cpu' | 'cuda'
  memoryBytes?: number
  uuid?: string
  logicalIndex?: number
}

export interface TrainingWorkerStatus {
  state: 'live' | 'stale' | 'unavailable'
  reason?: string
  sampledAt?: string
  versions?: Record<string, string>
}

export interface TrainingOptions {
  models: TrainingModel[]
  devices: TrainingDevice[]
  optimizers: string[]
  augmentations: { id: string; name: string; description: string }[]
  workerStatus?: TrainingWorkerStatus
}

export interface TrainingDatasetSummary {
  id: string
  name: string
  task: SelectableDatasetTask
  imageCount: number
  classCount: number
  splitCounts: Record<'train' | 'val' | 'test', number>
  annotatedSplitCounts: Record<'train' | 'val' | 'test', number>
  unassignedCount: number
  revision: string
  errors: { code: string; message: string }[]
  warnings: { code: string; message: string }[]
}

export interface TrainingResumeConfig {
  name: string
  deviceId?: string
  batchSize?: number
  workers?: number
  amp?: boolean
}

export interface TrainingArtifact {
  id: string
  name: string
  url: string
  kind: 'checkpoint' | 'report' | 'log' | 'preview' | 'manifest' | 'config' | 'metrics'
  sha256?: string
  sizeBytes?: number
}

export interface TrainingPreview {
  id: string
  name: string
  url: string
  groundTruthUrl?: string
  width?: number
  height?: number
}

export interface TrainingMetricPoint {
  sequence: number
  epoch: number
  values: Record<string, number>
  step?: number
  elapsedSeconds?: number
}

export interface TrainingLogEntry {
  sequence: number
  time: string
  level: 'info' | 'warn' | 'error' | 'metric'
  message: string
}

export interface TrainingRuntime {
  processId?: number
  versions?: Record<string, string>
  arguments?: Record<string, string | number | boolean>
}

export interface TrainingResources {
  state: 'waiting' | 'live' | 'stale' | 'unavailable' | 'finished'
  sample?: {
    sampledAt: string
    hostCpuPercent?: number
    hostMemoryUsedBytes?: number
    hostMemoryTotalBytes?: number
    memoryScope?: 'host' | 'container'
    processCpuPercent?: number
    processMemoryBytes?: number
    processId?: number
    gpu?: {
      deviceId: string
      name: string
      uuid?: string
      utilizationPercent?: number
      memoryUsedBytes?: number
      memoryTotalBytes?: number
      processMemoryBytes?: number
    }
  }
}

export interface TrainingTask {
  id: string
  config: TrainingConfig
  datasetName: string
  datasetImageCount?: number
  datasetClassCount?: number
  modelName: string
  architecture: string
  status: TrainingStatus
  phase?: string
  cancelRequested?: boolean
  createdAt: string
  startedAt?: string
  elapsedSeconds?: number
  etaSeconds?: number
  epoch: number
  metrics: Record<string, number>
  error?: string
  failure?: { code: string; stage: string; summary: string; exitCode?: number; suggestion?: string }
  snapshotDigest?: string
  modelVersion?: { id: string; version: string | number; sha256: string; validationStatus: string }
  parentModelVersionId?: string
  resumeFromTaskId?: string
  resume?: { available: boolean; reason?: string }
  actions: TrainingAction[]
  artifacts: TrainingArtifact[]
  device?: TrainingDevice
  runtime?: TrainingRuntime
  previews: TrainingPreview[]
}

export interface TrainingOverview {
  tasks: TrainingTask[]
  devices: TrainingDevice[]
  engine: string
  total: number
  page: number
  pageSize: number
  statusCounts: Partial<Record<TrainingStatus, number>>
  architectures: string[]
  elapsedTotal?: number
  averageScore?: number
  workerAvailable?: boolean
  workerStatus?: TrainingWorkerStatus
}

export interface TrainingFilters {
  status: TrainingStatus | 'all'
  task: SelectableDatasetTask | 'all'
  architecture: string
  query: string
  sort: 'newest' | 'progress' | 'metric' | 'duration'
  page: number
  pageSize: number
}

export interface TrainingPreflight {
  errors: { code: string; message: string }[]
  warnings: { code: string; message: string }[]
}
