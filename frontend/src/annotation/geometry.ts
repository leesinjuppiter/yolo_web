import type { Annotation } from '../domain'

export type Point = { x: number; y: number }
export type Bounds = { x: number; y: number; width: number; height: number }
export type Shape = Exclude<Annotation, { type: 'classify' }>
export const corners: Point[] = [{ x: -1, y: -1 }, { x: 1, y: -1 }, { x: 1, y: 1 }, { x: -1, y: 1 }]

export function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

export function bounds(points: Point[]): Bounds {
  if (!points.length) return { x: 0, y: 0, width: 0, height: 0 }
  const left = Math.min(...points.map(point => point.x))
  const top = Math.min(...points.map(point => point.y))
  const right = Math.max(...points.map(point => point.x))
  const bottom = Math.max(...points.map(point => point.y))
  return { x: left, y: top, width: right - left, height: bottom - top }
}

export function rotate(point: Point, degrees: number): Point {
  const radians = degrees * Math.PI / 180
  const cos = Math.cos(radians)
  const sin = Math.sin(radians)
  return { x: point.x * cos - point.y * sin, y: point.x * sin + point.y * cos }
}

export function boxHandles(shape: Extract<Shape, { type: 'bbox' | 'obb' | 'pose' }>) {
  const b = shape.type === 'obb'
    ? { x: shape.obb.cx, y: shape.obb.cy, width: shape.obb.width, height: shape.obb.height, angle: shape.obb.angle }
    : { ...shape.bbox, x: shape.bbox.x + shape.bbox.width / 2, y: shape.bbox.y + shape.bbox.height / 2, angle: 0 }
  return corners.map(corner => {
    const p = rotate({ x: corner.x * b.width / 2, y: corner.y * b.height / 2 }, b.angle)
    return { x: p.x + b.x, y: p.y + b.y }
  })
}

export function shapePoints(shape: Shape): Point[] {
  if (shape.type === 'polygon') return shape.polygon.map(([x, y]) => ({ x, y }))
  const handles = boxHandles(shape)
  return shape.type === 'pose'
    ? [...handles, ...shape.keypoints.filter(point => point.visible > 0)]
    : handles
}

export function move(shape: Shape, delta: Point, width: number, height: number): Shape {
  const b = bounds(shapePoints(shape))
  const x = clamp(delta.x, -b.x, width - b.x - b.width)
  const y = clamp(delta.y, -b.y, height - b.y - b.height)
  if (shape.type === 'polygon') return { ...shape, polygon: shape.polygon.map(([px, py]) => [px + x, py + y]) }
  if (shape.type === 'obb') return { ...shape, obb: { ...shape.obb, cx: shape.obb.cx + x, cy: shape.obb.cy + y } }
  const bbox = { ...shape.bbox, x: shape.bbox.x + x, y: shape.bbox.y + y }
  if (shape.type === 'pose') return {
    ...shape, bbox, keypoints: shape.keypoints.map(point => point.visible ? { ...point, x: point.x + x, y: point.y + y } : point),
  }
  return { ...shape, bbox }
}

export function normalizeAngle(angle: number) {
  return ((angle + 180) % 360 + 360) % 360 - 180
}

export function withinImage(shape: Shape, width: number, height: number) {
  const tolerance = 0.0001
  return shapePoints(shape).every(({ x, y }) => x >= -tolerance && y >= -tolerance && x <= width + tolerance && y <= height + tolerance)
}

export function polygonArea(points: Point[]) {
  const twiceArea = points.reduce((total, point, index) => {
    const next = points[(index + 1) % points.length]
    return total + point.x * next.y - next.x * point.y
  }, 0)
  return Math.abs(twiceArea) / 2
}
