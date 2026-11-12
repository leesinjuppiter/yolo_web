<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import type Konva from 'konva'
import { Circle, Group, Image as CanvasImage, Layer, Line, Rect, Stage, Text, type VueKonvaRef } from 'vue-konva'
import type { Annotation, DatasetClass, DatasetImage, TaskType } from '../domain'
import { bounds, boxHandles, clamp, corners, move, nearestEdge, nearestVertex, normalizeAngle, polygonArea, rotate, withinImage, type Point, type Shape } from './geometry'
import { createUuid } from '../utils/id'

export type AnnotationTool = 'select' | 'draw' | 'pan' | 'keypoint'

const props = defineProps<{
  image?: DatasetImage
  raster?: HTMLImageElement
  sourceState: 'loading' | 'ready' | 'error'
  annotations: Annotation[]
  hiddenAnnotationIds: ReadonlySet<string>
  classes: DatasetClass[]
  task: TaskType
  tool: AnnotationTool
  selectedId: string
  activeVertex?: number
  activeClassId: string
  activeKeypoint: string
  activeVisibility: 1 | 2
  keypointNames: string[]
  busy?: boolean
}>()
const emit = defineEmits<{
  select: [id: string]
  create: [annotation: Shape]
  update: [annotation: Shape]
  vertex: [index: number | undefined]
  keypoint: [id: string, name: string]
  zoom: [value: number]
  draft: [count: number]
}>()

type Drag =
  | { type: 'draw'; start: Point; current: Point }
  | { type: 'pan'; start: Point; center: Point }
  | { type: 'edit'; start: Point; original: Shape; handle: 'move' | 'resize' | 'rotate' | 'vertex' | 'keypoint'; index: number }
type ShapeNode = { key: string; component: typeof Rect | typeof Circle | typeof Line | typeof Text; config: Record<string, unknown> }

const holder = ref<HTMLDivElement>()
const stage = shallowRef<VueKonvaRef<Konva.Stage>>()
const raster = computed(() => props.raster)
const sourceState = computed(() => props.sourceState)
const viewport = ref({ width: 1, height: 1 })
const zoom = ref(1)
const center = ref<Point>({ x: 0, y: 0 })
const cursor = ref<Point>()
const polygon = ref<Point[]>([])
const drag = shallowRef<Drag>()
let pointer: number | undefined
let moved = false
let observer: ResizeObserver | undefined

const width = computed(() => props.image?.width || 1)
const height = computed(() => props.image?.height || 1)
const scale = computed(() => Math.min(viewport.value.width / width.value, viewport.value.height / height.value) * zoom.value)
const origin = computed(() => ({ x: viewport.value.width / 2 - center.value.x * scale.value, y: viewport.value.height / 2 - center.value.y * scale.value }))
const transform = computed(() => ({ ...origin.value, scaleX: scale.value, scaleY: scale.value }))
const unit = computed(() => 1 / scale.value)
const byClass = computed(() => new Map(props.classes.map(item => [item.id, item])))
const selectedPolygon = computed(() => props.annotations.find(
  item => item.type === 'polygon' && item.id === props.selectedId && !props.hiddenAnnotationIds.has(item.id),
))

watch([() => props.image?.id, () => props.image?.src], (_, previous) => {
  if (props.image?.id !== previous?.[0]) {
    cancelDraft()
    fit()
  }
}, { immediate: true })

watch(() => props.tool, () => cancelDraft())
watch(zoom, value => emit('zoom', value))
watch(() => polygon.value.length, count => emit('draft', count))

function fit() {
  zoom.value = 1
  center.value = { x: width.value / 2, y: height.value / 2 }
}

function zoomBy(factor: number, anchor = center.value) {
  if (drag.value) return
  const next = clamp(zoom.value * factor, 0.5, 8)
  const ratio = zoom.value / next
  center.value = {
    x: anchor.x + (center.value.x - anchor.x) * ratio,
    y: anchor.y + (center.value.y - anchor.y) * ratio,
  }
  zoom.value = next
}

function screen(event: MouseEvent): Point {
  const rect = holder.value?.getBoundingClientRect()
  return { x: event.clientX - (rect?.left ?? 0), y: event.clientY - (rect?.top ?? 0) }
}

function original(point: Point): Point {
  return { x: (point.x - origin.value.x) * unit.value, y: (point.y - origin.value.y) * unit.value }
}

function limit(point: Point): Point {
  return { x: clamp(point.x, 0, width.value), y: clamp(point.y, 0, height.value) }
}

function inImage(point: Point) {
  return point.x >= 0 && point.x <= width.value && point.y >= 0 && point.y <= height.value
}

function makeBase() {
  return { id: createUuid(), class_id: props.activeClassId, source: 'manual' as const }
}

function finishPolygon() {
  if (props.busy || polygon.value.length < 3 || polygonArea(polygon.value) < 1 || !props.activeClassId) return
  emit('create', { ...makeBase(), type: 'polygon', polygon: polygon.value.map(({ x, y }) => [x, y]) })
  polygon.value = []
}

function cancelDraft() {
  polygon.value = []
}

function doubleClick(event: MouseEvent) {
  if (props.tool === 'draw' && props.task === 'segment') {
    finishPolygon()
    return
  }
  const shape = selectedPolygon.value
  if (props.tool !== 'select' || props.busy || shape?.type !== 'polygon' || shape.polygon.length >= 4000) return
  const point = original(screen(event))
  if (nearestVertex(shape.polygon, point, 8 * unit.value) !== -1) return
  const edge = nearestEdge(shape.polygon, point, 7 * unit.value)
  if (!edge) return
  const index = edge.index + 1
  const points = [...shape.polygon]
  points.splice(index, 0, edge.point)
  emit('update', { ...shape, polygon: points })
  emit('vertex', index)
}

function removeVertex() {
  const shape = selectedPolygon.value
  const index = props.activeVertex
  if (props.tool !== 'select' || props.busy || drag.value || shape?.type !== 'polygon' ||
      index === undefined || shape.polygon.length <= 3) return
  const points = shape.polygon.filter((_, i) => i !== index)
  if (polygonArea(points.map(([x, y]) => ({ x, y }))) < 1) return
  emit('update', { ...shape, polygon: points })
  emit('vertex', undefined)
}

function nudgeAngle(delta: number) {
  const current = props.annotations.find(item => item.id === props.selectedId)
  if (current?.type !== 'obb' || props.busy || drag.value) return
  const next = { ...current, obb: { ...current.obb, angle: normalizeAngle(current.obb.angle + delta) } }
  if (withinImage(next, width.value, height.value)) emit('update', next)
}

defineExpose({ fit, zoomBy, finishPolygon, cancelDraft, nudgeAngle, removeVertex })

function placeKeypoint(point: Point) {
  const current = props.annotations.find(item => item.id === props.selectedId)
  if (current?.type !== 'pose' || props.hiddenAnnotationIds.has(current.id) || !props.activeKeypoint || !inImage(point)) return
  emit('update', {
    ...current,
    keypoints: current.keypoints.map(keypoint => keypoint.name === props.activeKeypoint
      ? { ...keypoint, x: point.x, y: point.y, visible: props.activeVisibility }
      : keypoint),
  })
  const index = props.keypointNames.indexOf(props.activeKeypoint)
  const next = props.keypointNames[index + 1]
  if (next) emit('keypoint', current.id, next)
}

function start(event: PointerEvent) {
  if (event.button !== 0 || pointer !== undefined || props.busy || !raster.value) return
  const location = screen(event)
  const point = original(location)
  const node = stage.value?.getNode().getIntersection(location)
  const id = node?.getAttr('annotationId') as string | undefined
  let annotation = props.annotations.find(item => item.id === id)
  let handle = (node?.getAttr('handle') ?? 'move') as Extract<Drag, { type: 'edit' }>['handle']
  let index = Number(node?.getAttr('handleIndex') ?? 0)
  const activePolygon = selectedPolygon.value
  if (props.tool === 'select' && activePolygon?.type === 'polygon') {
    const vertex = nearestVertex(activePolygon.polygon, point, 8 * unit.value)
    if (vertex >= 0) {
      annotation = activePolygon
      handle = 'vertex'
      index = vertex
    }
  }
  if (props.tool === 'pan') {
    drag.value = { type: 'pan', start: location, center: { ...center.value } }
  } else if (props.tool === 'keypoint') {
    placeKeypoint(point)
    return
  } else if (props.tool === 'draw') {
    if (!props.activeClassId || !inImage(point)) return
    if (props.task === 'segment') {
      const first = polygon.value[0]
      const last = polygon.value.at(-1)
      const near = (other?: Point) => !!other && Math.hypot(point.x - other.x, point.y - other.y) * scale.value <= 7
      if (polygon.value.length >= 3 && near(first)) finishPolygon()
      else if (event.detail < 2 && !near(last)) polygon.value = [...polygon.value, point]
      return
    }
    drag.value = { type: 'draw', start: point, current: point }
  } else if (annotation && annotation.type !== 'classify') {
    emit('select', annotation.id)
    emit('vertex', handle === 'vertex' ? index : undefined)
    if (handle === 'keypoint' && annotation.type === 'pose') {
      const point = annotation.keypoints[index]
      if (point) emit('keypoint', annotation.id, point.name)
    }
    drag.value = { type: 'edit', start: point, original: annotation, handle, index }
  } else {
    emit('select', '')
    return
  }
  pointer = event.pointerId
  moved = false
  holder.value?.setPointerCapture(pointer)
}

function resized(shape: Extract<Shape, { type: 'bbox' | 'obb' | 'pose' }>, index: number, delta: Point): Shape {
  const direction = corners[index]
  if (shape.type === 'obb') {
    const b = shape.obb
    const local = rotate(delta, -b.angle)
    const w = Math.max(1, b.width + direction.x * local.x)
    const h = Math.max(1, b.height + direction.y * local.y)
    const shift = rotate({ x: direction.x * (w - b.width) / 2, y: direction.y * (h - b.height) / 2 }, b.angle)
    return { ...shape, obb: { ...b, cx: b.cx + shift.x, cy: b.cy + shift.y, width: w, height: h } }
  }
  const b = shape.bbox
  const x = direction.x < 0 ? clamp(b.x + delta.x, 0, b.x + b.width - 1) : b.x
  const y = direction.y < 0 ? clamp(b.y + delta.y, 0, b.y + b.height - 1) : b.y
  const right = direction.x > 0 ? clamp(b.x + b.width + delta.x, x + 1, width.value) : b.x + b.width
  const bottom = direction.y > 0 ? clamp(b.y + b.height + delta.y, y + 1, height.value) : b.y + b.height
  return { ...shape, bbox: { x, y, width: right - x, height: bottom - y } }
}

function updateShape(current: Extract<Drag, { type: 'edit' }>, point: Point) {
  const shape = current.original
  const delta = { x: point.x - current.start.x, y: point.y - current.start.y }
  let next: Shape
  if (current.handle === 'resize' && shape.type !== 'polygon') {
    next = resized(shape, current.index, delta)
  } else if (current.handle === 'rotate' && shape.type === 'obb') {
    const { cx, cy, angle } = shape.obb
    const first = Math.atan2(current.start.y - cy, current.start.x - cx)
    const last = Math.atan2(point.y - cy, point.x - cx)
    next = { ...shape, obb: { ...shape.obb, angle: normalizeAngle(angle + (last - first) * 180 / Math.PI) } }
  } else if (current.handle === 'vertex' && shape.type === 'polygon') {
    const [x, y] = shape.polygon[current.index]
    const vertex = limit({ x: x + delta.x, y: y + delta.y })
    const points = shape.polygon.map(([x, y], index) => index === current.index ? vertex : { x, y })
    if (polygonArea(points) < 1) return
    next = { ...shape, polygon: points.map(({ x, y }) => [x, y]) }
  } else if (current.handle === 'keypoint' && shape.type === 'pose') {
    const location = limit(point)
    next = { ...shape, keypoints: shape.keypoints.map((keypoint, index) => index === current.index ? { ...keypoint, ...location } : keypoint) }
  } else {
    next = move(shape, delta, width.value, height.value)
  }
  if (withinImage(next, width.value, height.value)) emit('update', next)
}

function track(event: PointerEvent) {
  const location = screen(event)
  const point = original(location)
  cursor.value = point
  const current = drag.value
  if (!current || pointer !== event.pointerId) return
  if (current.type === 'pan') {
    center.value = {
      x: current.center.x - (location.x - current.start.x) * unit.value,
      y: current.center.y - (location.y - current.start.y) * unit.value,
    }
  } else if (current.type === 'draw') {
    drag.value = { ...current, current: limit(point) }
  } else if (moved || Math.hypot(point.x - current.start.x, point.y - current.start.y) * scale.value >= 1) {
    moved = true
    updateShape(current, point)
  }
}

function stop(event: PointerEvent, cancel = false) {
  if (pointer !== event.pointerId) return
  if (!cancel) track(event)
  const current = drag.value
  pointer = undefined
  drag.value = undefined
  if (holder.value?.hasPointerCapture(event.pointerId)) holder.value.releasePointerCapture(event.pointerId)
  if (cancel && current?.type === 'edit') emit('update', current.original)
  if (cancel && current?.type === 'pan') center.value = current.center
  if (cancel || current?.type !== 'draw') return
  const bbox = bounds([current.start, current.current])
  if (bbox.width < 1 || bbox.height < 1 || Math.min(bbox.width, bbox.height) * scale.value < 4) return
  const base = makeBase()
  if (props.task === 'obb') {
    emit('create', { ...base, type: 'obb', obb: { cx: bbox.x + bbox.width / 2, cy: bbox.y + bbox.height / 2, width: bbox.width, height: bbox.height, angle: 0 } })
  } else if (props.task === 'pose') {
    emit('create', { ...base, type: 'pose', bbox, keypoints: props.keypointNames.map(name => ({ name, x: 0, y: 0, visible: 0 })) })
  } else if (props.task === 'detect') {
    emit('create', { ...base, type: 'bbox', bbox })
  }
}


const nodes = computed<ShapeNode[]>(() => {
  const shapes: ShapeNode[] = []
  const handles: ShapeNode[] = []
  const u = unit.value
  const add = (component: ShapeNode['component'], key: string, config: ShapeNode['config']) => {
    shapes.push({ key, component, config })
  }
  for (const [index, annotation] of props.annotations.entries()) {
    if (annotation.type === 'classify' || props.hiddenAnnotationIds.has(annotation.id)) continue
    const { id } = annotation
    const selected = id === props.selectedId
    const color = byClass.value.get(annotation.class_id)?.color ?? '#748396'
    const fill = color + (selected ? '2c' : '14')
    const line = { annotationId: id, stroke: color, fill, strokeWidth: (selected ? 2 : 1.35) * u }
    const label = '#' + (index + 1) + ' ' + (byClass.value.get(annotation.class_id)?.name ?? '未知类别')
    let anchor: Point
    if (annotation.type === 'polygon') {
      const points = annotation.polygon.map(([x, y]) => ({ x, y }))
      anchor = bounds(points)
      add(Line, id, { ...line, points: annotation.polygon.flat(), closed: true, hitStrokeWidth: 12 * u })
    } else if (annotation.type === 'obb') {
      const box = annotation.obb
      anchor = boxHandles(annotation).reduce((top, point) =>
        (Math.abs(point.y - top.y) < u ? point.x < top.x : point.y < top.y) ? point : top,
      )
      add(Rect, id, { ...line, x: box.cx, y: box.cy, width: box.width, height: box.height, rotation: box.angle,
        offsetX: box.width / 2, offsetY: box.height / 2 })
    } else {
      anchor = annotation.bbox
      add(Rect, id, { ...line, ...annotation.bbox })
    }
    const alignLeftOfCorner = annotation.type === 'obb' && anchor.x > width.value / 2
    add(Text, id + '-label', {
      text: label, x: anchor.x + 3 * u, y: Math.max(0, anchor.y - 16 * u),
      ...(alignLeftOfCorner ? { x: 0, width: anchor.x - 3 * u, align: 'right', wrap: 'none' } : {}),
      fill: color, stroke: '#fff', strokeWidth: 2 * u, fillAfterStrokeEnabled: true,
      listening: false, fontStyle: 'bold', fontSize: 12 * u,
    })
    if (annotation.type === 'pose') {
      annotation.keypoints.forEach((point, pointIndex) => {
        if (!point.visible) return
        add(Circle, id + '-point-' + pointIndex, {
          x: point.x, y: point.y, radius: (selected && point.name === props.activeKeypoint ? 6 : 4) * u,
          fill: point.visible === 2 ? color : '#fff', stroke: color, strokeWidth: 2 * u,
          annotationId: id, handle: 'keypoint', handleIndex: pointIndex,
        })
        if (selected) add(Text, id + '-point-label-' + pointIndex, {
          text: point.name, x: point.x + 8 * u, y: point.y - 10 * u, fill: color,
          stroke: '#fff', strokeWidth: 2 * u, fillAfterStrokeEnabled: true, fontSize: 11 * u, listening: false,
        })
      })
    }
    if (!selected || props.tool !== 'select') continue
    const points = annotation.type === 'polygon'
      ? annotation.polygon.map(([x, y]) => ({ x, y }))
      : boxHandles(annotation)
    points.forEach((point, pointIndex) => handles.push({
      key: id + '-handle-' + pointIndex, component: Rect,
      config: {
        x: point.x - 4 * u, y: point.y - 4 * u, width: 8 * u, height: 8 * u,
        fill: annotation.type === 'polygon' && pointIndex === props.activeVertex ? color : '#fff', stroke: color, strokeWidth: 1.5 * u,
        annotationId: id, handle: annotation.type === 'polygon' ? 'vertex' : 'resize', handleIndex: pointIndex,
      },
    }))
    if (annotation.type === 'obb') {
      const { cx, cy, height: h, angle } = annotation.obb
      const edge = rotate({ x: 0, y: -h / 2 }, angle)
      const point = rotate({ x: 0, y: -h / 2 - 20 * u }, angle)
      handles.push(
        { key: id + '-stem', component: Line, config: {
          points: [edge.x + cx, edge.y + cy, point.x + cx, point.y + cy], stroke: color, strokeWidth: u, listening: false,
        } },
        { key: id + '-rotate', component: Circle, config: {
          x: cx + point.x, y: cy + point.y, radius: 5 * u, fill: '#fff', stroke: color,
          strokeWidth: 1.5 * u, annotationId: id, handle: 'rotate',
        } },
      )
    }
  }
  return [...shapes, ...handles]
})

const preview = computed(() => {
  const color = byClass.value.get(props.activeClassId)?.color ?? '#4f6885'
  const u = unit.value
  const current = drag.value
  return {
    rect: current?.type === 'draw'
      ? { ...bounds([current.start, current.current]), fill: color + '22', stroke: color, strokeWidth: 1.5 * u, listening: false }
      : undefined,
    line: polygon.value.length ? {
      points: [...polygon.value, ...(cursor.value && inImage(cursor.value) ? [cursor.value] : [])].flatMap(point => [point.x, point.y]),
      stroke: color, strokeWidth: 1.5 * u, dash: [5 * u, 3 * u], listening: false,
    } : undefined,
    vertices: polygon.value.map((point, index) => ({
      ...point, radius: (index === 0 ? 5 : 3) * u, fill: '#fff', stroke: color, strokeWidth: u, listening: false,
    })),
  }
})

onMounted(() => {
  observer = new ResizeObserver(entries => {
    const rect = entries[0]?.contentRect
    if (rect?.width && rect.height) viewport.value = { width: Math.floor(rect.width), height: Math.floor(rect.height) }
  })
  if (holder.value) observer.observe(holder.value)
})

onUnmounted(() => observer?.disconnect())
</script>

<template>
  <div ref="holder" class="annotation-canvas" :class="tool" data-testid="annotation-canvas"
    @pointerdown="start" @pointermove="track" @pointerup="stop($event)" @pointercancel="stop($event, true)"
    @lostpointercapture="stop($event, true)" @pointerleave="cursor = undefined"
    @wheel.prevent="zoomBy($event.deltaY < 0 ? 1.12 : 1 / 1.12, original(screen($event)))"
    @dblclick="doubleClick">
    <Stage ref="stage" :config="viewport">
      <Layer>
        <Group v-if="raster" :config="transform">
          <CanvasImage :config="{ image: raster, width, height, listening: false }" />
          <component :is="node.component" v-for="node in nodes" :key="node.key" :config="node.config" />
          <Rect v-if="preview.rect" :config="preview.rect" />
          <Line v-if="preview.line" :config="preview.line" />
          <Circle v-for="(point, index) in preview.vertices" :key="'draft-' + index" :config="point" />
        </Group>
      </Layer>
    </Stage>
    <p v-if="!raster" class="canvas-empty">
      {{ !image ? '当前分集暂无图片。' : !image.src || sourceState === 'error' ? '这张图片暂时无法预览。' : '正在加载原图…' }}
    </p>
    <span v-if="cursor && raster && inImage(cursor)" class="coordinate">X: {{ Math.round(cursor.x) }}　Y: {{ Math.round(cursor.y) }}</span>
  </div>
</template>

<style scoped>
.annotation-canvas { position:absolute; inset:0; overflow:hidden; touch-action:none; user-select:none; }
.annotation-canvas.draw, .annotation-canvas.keypoint { cursor:crosshair; }
.annotation-canvas.pan { cursor:grab; }
.annotation-canvas.pan:active { cursor:grabbing; }
.canvas-empty { position:absolute; left:50%; top:50%; transform:translate(-50%,-50%); margin:0; padding:10px 14px; border:1px solid var(--line,#c3c6ce); background:var(--surface,#fff); color:var(--muted,#5c6775); white-space:nowrap; pointer-events:none; }
.coordinate { position:absolute; right:5px; bottom:5px; padding:3px 5px; background:#f8faff; color:var(--muted,#5c6775); font:11px ui-monospace, monospace; pointer-events:none; }
</style>
