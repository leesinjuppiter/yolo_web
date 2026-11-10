import type { Annotation, AnnotationStatus, Dataset, DatasetClass, DatasetImage, DatasetReport, ReportKind, Split, TaskType } from '../domain'

type DatasetResponse = {
  id: string
  name: string
  task_type: TaskType
  created_at: string
  keypoint_names: string[]
  classes: DatasetClass[]
  images: (Omit<DatasetImage, 'src'> & { url: string })[]
}

const root = '/api/datasets'
const at = (id: string) => `${root}/${encodeURIComponent(id)}`

async function request(url: string, init?: RequestInit): Promise<Response> {
  let response: Response
  try {
    response = await fetch(url, init)
  } catch {
    throw new Error('无法连接标注后端，请确认服务已启动。')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    const reason = typeof detail === 'string'
      ? detail
      : Array.isArray(detail) ? detail.map(item => `${item.loc?.slice(1).join('.')}: ${item.msg}`).join('；') : detail?.message
    throw new Error(reason || `请求失败（HTTP ${response.status}）`)
  }
  return response
}

const json = (method: string, value: unknown): RequestInit => ({
  method, body: JSON.stringify(value), headers: { 'Content-Type': 'application/json' },
})

function adapt(record: DatasetResponse): Dataset {
  return {
    id: record.id, name: record.name, task: record.task_type, createdAt: record.created_at,
    keypointNames: record.keypoint_names, classes: record.classes,
    images: record.images.map(({ url, ...image }) => ({ ...image, src: url })),
  }
}

async function dataset(url: string, init: RequestInit) {
  return adapt(await (await request(url, init)).json() as DatasetResponse)
}

export async function listDatasets() {
  return ((await (await request(root)).json()) as DatasetResponse[]).map(adapt)
}

export function createDataset(name: string, task: TaskType, keypointNames: string[]) {
  return dataset(root, json('POST', { name, task_type: task, keypoint_names: keypointNames }))
}

export async function deleteDataset(id: string) {
  await request(at(id), { method: 'DELETE' })
}

export function uploadImages(id: string, files: File[], split: Split | null) {
  const form = new FormData()
  for (const file of files) form.append('files', file)
  if (split) form.set('split', split)
  return dataset(`${at(id)}/images`, { method: 'POST', body: form })
}

export async function deleteDatasetImage(id: string, imageId: string) {
  await request(`${at(id)}/images/${encodeURIComponent(imageId)}`, { method: 'DELETE' })
}

export function saveSplits(id: string, splits: Record<string, Split | null>) {
  return dataset(`${at(id)}/splits`, json('PATCH', { splits }))
}

export async function updateDatasetClass(id: string, entry: DatasetClass, name: string, color: string): Promise<DatasetClass> {
  const previous = { name: entry.name, color: entry.color }
  return (await request(`${at(id)}/classes/${encodeURIComponent(entry.id)}`, json('PATCH', { name, color, previous }))).json()
}

export function updateAnnotations(id: string, image: DatasetImage, annotations: Annotation[], classes: DatasetClass[], status: AnnotationStatus) {
  const cleanClasses = classes.map(({ id, name, color }) => ({ id, name, color }))
  return dataset(`${at(id)}/images/${encodeURIComponent(image.id)}/annotations`,
    json('PUT', { version: image.version, status, annotations, classes: cleanClasses }))
}

export async function readReport(id: string, kind: ReportKind): Promise<Pick<DatasetReport, 'title' | 'items' | 'messages' | 'issues'>> {
  return (await request(`${at(id)}/reports/${kind}`)).json()
}

type ImportFormat = 'yolo' | 'coco'

export function importDatasetArchive(file: File, task: TaskType, format: ImportFormat) {
  const form = new FormData()
  form.append('file', file)
  form.append('task_type', task)
  return dataset(`${root}/import/${format}`, { method: 'POST', body: form })
}

export type LocalDirectoryListing = {
  path: string | null
  parent: string | null
  directories: { name: string; path: string }[]
}

export async function listLocalDirectories(path?: string): Promise<LocalDirectoryListing> {
  const query = path ? '?' + new URLSearchParams({ path }) : ''
  return (await request(`${root}/import/directories${query}`)).json()
}

export function importDatasetDirectory(path: string, task: TaskType, format: ImportFormat) {
  return dataset(`${root}/import/${format}-directory`, json('POST', { path, task_type: task }))
}

export async function downloadYolo(id: string, includeImages: boolean, includeNegative: boolean) {
  const query = new URLSearchParams({ include_images: String(includeImages), include_negative: String(includeNegative) })
  const response = await request(`${at(id)}/export/yolo?${query}`)
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = `dataset-${id}.zip`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
