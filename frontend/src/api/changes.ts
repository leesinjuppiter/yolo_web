export type Change = { topic: string; table?: string; id?: string; kind?: string }
export type ConnectionState = 'connecting' | 'connected' | 'reconnecting'
type Subscriber = { change: (value: Change | null) => void; state?: (value: ConnectionState) => void }

const subscribers = new Set<Subscriber>()
let source: EventSource | undefined
let state: ConnectionState = 'connecting'

function updateState(value: ConnectionState) {
  state = value
  for (const subscriber of subscribers) subscriber.state?.(value)
}

function connect() {
  source = new EventSource('/api/changes')
  source.onerror = () => updateState('reconnecting')
  source.addEventListener('status', () => updateState('reconnecting'))
  source.addEventListener('sync', () => {
    updateState('connected')
    for (const subscriber of subscribers) subscriber.change(null)
  })
  source.addEventListener('change', event => {
    const value = JSON.parse((event as MessageEvent).data) as Change
    for (const subscriber of subscribers) subscriber.change(value)
  })
}

function recover() {
  source?.close()
  updateState('connecting')
  connect()
}

export function observeChanges(change: Subscriber['change'], onState?: Subscriber['state']) {
  const subscriber = { change, state: onState }
  subscribers.add(subscriber)
  onState?.(state)
  if (!source) {
    connect()
    window.addEventListener('online', recover)
  }
  return () => {
    subscribers.delete(subscriber)
    if (!subscribers.size) {
      source?.close()
      source = undefined
      state = 'connecting'
      window.removeEventListener('online', recover)
    }
  }
}

// Merge bursts, and retain changes arriving while a request is in flight.
export function changeRefresh(refresh: () => Promise<unknown>, delay = 300) {
  let timer: ReturnType<typeof setTimeout> | undefined
  let running = false, pending = false, stopped = false
  async function run() {
    timer = undefined
    if (stopped || running || !pending) return
    pending = false
    running = true
    try { await refresh() } finally {
      running = false
      if (pending && !stopped) timer = setTimeout(run, delay)
    }
  }
  return {
    notify() {
      if (stopped) return
      pending = true
      if (!running && timer === undefined) timer = setTimeout(run, delay)
    },
    stop() { stopped = true; clearTimeout(timer) },
  }
}

export function refreshOnChanges(topics: string[], refresh: () => Promise<unknown>, accepts?: (change: Change) => boolean) {
  const updates = changeRefresh(refresh)
  const unsubscribe = observeChanges(change => {
    if (!change || (topics.includes(change.topic) && (!accepts || accepts(change)))) updates.notify()
  })
  return () => { unsubscribe(); updates.stop() }
}
