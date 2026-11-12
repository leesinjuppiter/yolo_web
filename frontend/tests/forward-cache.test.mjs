import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ForwardImageCache } from '../src/annotation/forward-cache.ts'

test('continues beyond the nearby window in order, skips ready images, and reports actual completion', async () => {
  const requested = [], progress = []
  let inFlight = 0, maximum = 0
  const queue = new ForwardImageCache(async src => {
    inFlight++; maximum = Math.max(maximum, inFlight)
    requested.push(src)
    await new Promise(resolve => setImmediate(resolve))
    inFlight--
  })
  queue.markReady('next')
  await queue.warm(['next', 'third', 'fourth', 'fourth'], value => progress.push(value))
  assert.deepEqual(requested, ['third', 'fourth'])
  assert.equal(maximum, 1)
  assert.deepEqual(progress[0], { loaded: 1, total: 3, failed: 0, done: false })
  assert.deepEqual(progress.at(-1), { loaded: 3, total: 3, failed: 0, done: true })
  await queue.warm(['next', 'third', 'fourth'], () => {})
  assert.equal(requested.length, 2)
})

test('failed image does not block later images and retry only fetches the failed image', async () => {
  const requested = []
  let first = true, last
  const queue = new ForwardImageCache(async src => {
    requested.push(src)
    if (src === 'bad' && first) { first = false; throw new Error('offline') }
  })
  await queue.warm(['bad', 'later'], value => { last = value })
  assert.deepEqual(last, { loaded: 1, total: 2, failed: 1, done: true })
  await queue.warm(['bad', 'later'], value => { last = value })
  assert.deepEqual(requested, ['bad', 'later', 'bad'])
  assert.deepEqual(last, { loaded: 2, total: 2, failed: 0, done: true })
})

test('changing position aborts the old download and old queue cannot publish late progress', async () => {
  const requested = [], oldProgress = []
  const queue = new ForwardImageCache((src, signal) => {
    requested.push(src)
    if (src === 'new') return Promise.resolve()
    return new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))))
  })
  const old = queue.warm(['old', 'obsolete'], value => oldProgress.push(value))
  await queue.warm(['new'], () => {})
  await old
  assert.deepEqual(requested, ['old', 'new'])
  assert.equal(oldProgress.length, 1)
})

test('browser-cache warming drains the response with low priority and without image decoding', async () => {
  const original = globalThis.fetch
  let options, chunks = 0
  globalThis.fetch = async (_, init) => {
    options = init
    return new Response(new ReadableStream({ pull(controller) {
      if (chunks++ < 2) controller.enqueue(new Uint8Array([1, 2, 3]))
      else controller.close()
    } }))
  }
  try {
    let last
    await new ForwardImageCache().warm(['/image'], value => { last = value })
    assert.equal(options.cache, 'force-cache')
    assert.equal(options.priority, 'low')
    assert.equal(chunks, 3)
    assert.deepEqual(last, { loaded: 1, total: 1, failed: 0, done: true })
  } finally { globalThis.fetch = original }
})
