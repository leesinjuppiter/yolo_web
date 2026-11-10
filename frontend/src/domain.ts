export type TaskType = 'detect' | 'segment' | 'obb' | 'classify' | 'pose'
export const selectableDatasetTasks = ['detect', 'segment', 'obb', 'classify'] as const satisfies readonly TaskType[]
export type SelectableDatasetTask = (typeof selectableDatasetTasks)[number]
export type Split = 'train' | 'val' | 'test'
export type DatasetAction = 'add' | 'annotate' | 'export' | 'validate' | 'duplicates' | 'quality' | 'delete' | 'auto' | 'train' | 'assistant' | 'splits' | 'excluded'
export type DialogKind = 'create' | 'add' | 'import' | 'export' | 'delete' | 'auto' | 'splits'
export type ReportKind = 'validate' | 'duplicates' | 'quality'

export interface DatasetClass {
  id: string
  name: string
  color: string
  index?: number
}

export type AnnotationStatus = 'unlabeled' | 'negative' | 'annotated'
export const annotationStatusLabels: Record<AnnotationStatus, string> = { unlabeled: '未标注', negative: '负样本', annotated: '已标注' }
export interface BoundingBox { x: number; y: number; width: number; height: number }
export interface Keypoint { name: string; x: number; y: number; visible: 0 | 1 | 2 }
export type Annotation = {
  id: string
  class_id: string
  source: 'manual' | 'sam' | 'imported'
} & (
  | { type: 'bbox'; bbox: BoundingBox }
  | { type: 'polygon'; polygon: [number, number][] }
  | { type: 'obb'; obb: { cx: number; cy: number; width: number; height: number; angle: number } }
  | { type: 'pose'; bbox: BoundingBox; keypoints: Keypoint[] }
  | { type: 'classify' }
)

export interface DatasetImage {
  id: string
  name: string
  split: Split | null
  width: number
  height: number
  src?: string
  status: AnnotationStatus
  version: number
  annotations: Annotation[]
}

export type SimilarityDecision = 'keep_both' | 'discard_image' | 'discard_related'

export interface ReportIssue {
  image_id?: string | null
  related_image_id?: string | null
  image_sha256?: string | null
  related_image_sha256?: string | null
  review_status?: 'pending' | 'confirmed' | null
  message: string
  code: string
  severity: 'error' | 'warning'
}

interface Counts {
  images: number
  annotated: number
  classes: number
}

export interface Dataset {
  id: string
  name: string
  task: TaskType
  createdAt: string
  keypointNames: string[]
  images: DatasetImage[]
  classes: DatasetClass[]
}

export interface ReportResult {
  title?: string
  items?: { label: string; value: string | number }[]
  messages?: string[]
  issues?: ReportIssue[]
  class_counts?: Record<string, number>
}

export interface ReportSnapshot {
  status: 'idle' | 'queued' | 'running' | 'ready' | 'failed'
  stale: boolean
  generated_at: string | null
  progress: { completed: number; total: number } | null
  error: string | null
  report: ReportResult | null
}

export interface DatasetReport extends ReportResult {
  datasetId: string
  kind: ReportKind
  pending: boolean
  status: ReportSnapshot['status'] | 'loading'
  stale: boolean
  generatedAt: string | null
  progress: ReportSnapshot['progress']
  error: string | null
}

export const taskLabels: Record<TaskType, string> = {
  detect: '目标检测',
  segment: '实例分割',
  obb: '旋转框（OBB）',
  classify: '图像分类',
  pose: '姿态估计',
}

export function datasetCounts(dataset: Dataset): Counts {
  return {
    images: dataset.images.length,
    annotated: dataset.images.filter(image => image.status !== 'unlabeled').length,
    classes: dataset.classes.length,
  }
}
