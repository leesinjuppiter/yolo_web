export type TaskType = 'detect' | 'segment' | 'obb' | 'classify' | 'pose'
export type Split = 'train' | 'val' | 'test'
export type DatasetAction = 'add' | 'annotate' | 'export' | 'validate' | 'duplicates' | 'quality' | 'delete' | 'auto' | 'train' | 'assistant' | 'splits'
export type DialogKind = 'create' | 'add' | 'import' | 'export' | 'delete' | 'auto' | 'splits'
export type ReportKind = 'validate' | 'duplicates' | 'quality'

export interface DatasetClass {
  id: string
  name: string
  color: string
  index?: number
}

export type AnnotationStatus = 'unlabeled' | 'negative' | 'annotated'
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

export interface DatasetReport {
  datasetId: string
  kind: ReportKind
  pending: boolean
  title?: string
  items?: { label: string; value: string | number }[]
  messages?: string[]
  issues?: { image_id?: string | null; message: string; code: string }[]
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
