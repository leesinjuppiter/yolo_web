export type ModuleKey = 'datasets' | 'training' | 'models' | 'deployments' | 'active-learning'
export type PreloadStep = { key: ModuleKey; label: string; load: (signal: AbortSignal) => Promise<unknown> }
export type StepState = { key: ModuleKey; label: string; status: 'waiting' | 'loading' | 'ready' | 'failed'; error: string }
type Entry = { value: unknown; stale: boolean }

// These seeds are consumed once. Existing page refresh/subscription logic stays in charge afterwards.
export class PagePreloader {
  private entries = new Map<ModuleKey, Entry>()
  private revisions = new Map<ModuleKey, number>()
  private controllers = new Set<AbortController>()
  private running = false
  private steps: PreloadStep[]
  private timeoutMs: number
  readonly states: StepState[]

  constructor(steps: PreloadStep[], timeoutMs = 120_000) {
    this.steps = steps
    this.timeoutMs = timeoutMs
    this.states = steps.map(({ key, label }) => ({ key, label, status: 'waiting', error: '' }))
  }

  async run(update: (states: StepState[]) => void) {
    if (this.running) return false
    this.running = true
    const emit = () => update(this.states.map(state => ({ ...state })))
    await Promise.all(this.steps.map(async (step, index) => {
      const state = this.states[index]!
      if (state.status === 'ready') return
      state.status = 'loading'; state.error = ''; emit()
      const revision = this.revisions.get(step.key) ?? 0
      const controller = new AbortController()
      this.controllers.add(controller)
      const timer = setTimeout(() => controller.abort(), this.timeoutMs)
      try {
        const interrupted = new Promise<never>((_, reject) => {
          controller.signal.addEventListener('abort', () => reject(new Error('加载已中断')), { once: true })
        })
        const value = await Promise.race([step.load(controller.signal), interrupted])
        if (controller.signal.aborted) throw new Error('加载超时，请重试')
        this.entries.set(step.key, { value, stale: revision !== (this.revisions.get(step.key) ?? 0) })
        state.status = 'ready'
      } catch (cause) {
        state.status = 'failed'
        state.error = controller.signal.aborted ? '加载超时或已中断，请重试'
          : cause instanceof Error ? cause.message : '加载失败，请重试'
      } finally {
        clearTimeout(timer); this.controllers.delete(controller); emit()
      }
    }))
    this.running = false
    return this.states.every(state => state.status === 'ready')
  }

  invalidate(keys: ModuleKey[]) {
    for (const key of keys) {
      this.revisions.set(key, (this.revisions.get(key) ?? 0) + 1)
      const entry = this.entries.get(key)
      if (entry) entry.stale = true
    }
  }

  take<T>(key: ModuleKey): { value: T; stale: boolean } | undefined {
    const entry = this.entries.get(key)
    this.entries.delete(key)
    return entry as { value: T; stale: boolean } | undefined
  }

  cancel() { for (const controller of this.controllers) controller.abort() }
}
