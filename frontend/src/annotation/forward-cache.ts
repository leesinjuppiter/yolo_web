export type CacheProgress = { loaded: number; total: number; failed: number; done: boolean }

async function warmImage(src: string, signal: AbortSignal) {
  const options: RequestInit & { priority: 'low' } = { signal, cache: 'force-cache', priority: 'low' }
  const response = await fetch(src, options)
  if (!response.ok) throw new Error('图片预加载失败')
  // Consume the response to populate the browser cache without retaining decoded pixels.
  const reader = response.body?.getReader()
  if (reader) {
    try { while (!(await reader.read()).done) { /* Discard each downloaded chunk. */ } }
    finally { reader.releaseLock() }
  } else await response.arrayBuffer()
}

export class ForwardImageCache {
  private completed = new Set<string>()
  private controller: AbortController | undefined
  private load: typeof warmImage

  constructor(load = warmImage) { this.load = load }

  markReady(src: string) { this.completed.add(src) }
  stop() { this.controller?.abort() }

  async warm(sources: string[], update: (progress: CacheProgress) => void) {
    this.stop()
    const controller = new AbortController()
    this.controller = controller
    const unique = [...new Set(sources)]
    let failed = 0
    const emit = (done = false) => update({ loaded: unique.filter(src => this.completed.has(src)).length,
      total: unique.length, failed, done })
    emit()
    for (const src of unique) {
      if (controller.signal.aborted) return
      if (this.completed.has(src)) continue
      try {
        await this.load(src, controller.signal)
        if (controller.signal.aborted) return
        this.completed.add(src)
      } catch {
        if (controller.signal.aborted) return
        failed++
      }
      emit()
    }
    if (!controller.signal.aborted) emit(true)
  }
}
