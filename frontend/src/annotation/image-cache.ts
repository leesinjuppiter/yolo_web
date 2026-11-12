type Entry = { image: HTMLImageElement; promise: Promise<HTMLImageElement>; ready: boolean; cancel: () => void }

export class AnnotationImageCache {
  private entries = new Map<string, Entry>()

  ready(src: string) { const entry = this.entries.get(src); return entry?.ready ? entry.image : undefined }

  load(src: string, priority: 'high' | 'low' = 'low') {
    const existing = this.entries.get(src)
    if (existing) {
      if (priority === 'high') existing.image.fetchPriority = 'high'
      return existing.promise
    }
    const image = new Image()
    image.fetchPriority = priority
    let cancelled = false, cancel = () => {}
    const promise = new Promise<HTMLImageElement>((resolve, reject) => {
      const fail = () => {
        image.onload = image.onerror = null
        this.entries.delete(src); reject(new Error('图片加载失败，请重试'))
      }
      image.onload = async () => {
        try {
          await image.decode()
          if (cancelled) return
          const entry = this.entries.get(src)
          if (entry) entry.ready = true
          image.onload = image.onerror = null
          resolve(image)
        } catch { if (!cancelled) fail() }
      }
      image.onerror = fail
      cancel = () => {
        cancelled = true
        image.onload = image.onerror = null
        image.src = ''
        reject(new DOMException('图片缓存已取消', 'AbortError'))
      }
    })
    this.entries.set(src, { image, promise, ready: false, cancel })
    image.src = src
    return promise
  }

  retain(sources: string[]) {
    for (const [src, entry] of this.entries) {
      if (!sources.includes(src)) {
        this.entries.delete(src)
        if (!entry.ready) entry.cancel()
      }
    }
  }

  clear() { this.retain([]) }
}

export function nearbyImages<T extends { width: number; height: number; src?: string }>(images: T[], index: number) {
  if (index < 0 || !images[index]?.src) return []
  const result: T[] = []
  let bytes = 0
  for (const item of [images[index], images[index + 1], images[index - 1]]) {
    if (!item?.src) continue
    const size = item.width * item.height * 4
    if (result.length && bytes + size > 128 * 1024 ** 2) continue
    result.push(item); bytes += size
  }
  return result
}

export const thumbnailUrl = (src?: string) => src?.replace(/(\/api\/datasets\/[^/]+\/images\/[^/]+)\/content$/, '$1/thumbnail')
