import assert from 'node:assert/strict'
import { test } from 'node:test'
import { setTimeout as wait } from 'node:timers/promises'
import { changeRefresh, observeChanges, refreshOnChanges } from '../src/api/changes.ts'

class FakeSource {
  static instances = []
  handlers = new Map()
  closed = false
  constructor(url) { this.url = url; FakeSource.instances.push(this) }
  addEventListener(name, callback) { this.handlers.set(name, callback) }
  emit(name, value = {}) { this.handlers.get(name)?.({ data: JSON.stringify(value) }) }
  close() { this.closed = true }
}
globalThis.EventSource = FakeSource
globalThis.window = new EventTarget()

test('shares one stream; reconnect syncs and final unsubscribe closes it', () => {
  const states = [], changes = []
  const before = FakeSource.instances.length
  const a = observeChanges(change => changes.push(change), state => states.push(state))
  const b = observeChanges(() => {})
  assert.equal(FakeSource.instances.length, before + 1)
  const source = FakeSource.instances.at(-1)
  assert.equal(source.url, '/api/changes')
  source.emit('sync')
  source.emit('change', { topic: 'training', id: 'one' })
  source.onerror()
  source.emit('sync')
  assert.deepEqual(changes, [null, { topic: 'training', id: 'one' }, null])
  assert.deepEqual(states, ['connecting', 'connected', 'reconnecting', 'connected'])
  a(); assert.equal(source.closed, false)
  b(); assert.equal(source.closed, true)
})

test('browser online recovery opens a new stream and waits for server sync', () => {
  let count = 0
  const stop = observeChanges(() => { count++ })
  const old = FakeSource.instances.at(-1)
  window.dispatchEvent(new Event('online'))
  assert.equal(old.closed, true)
  assert.equal(count, 0)
  FakeSource.instances.at(-1).emit('sync')
  assert.equal(count, 1)
  stop()
})

test('merges bursts, retains in-flight invalidations, and stops without polling', async () => {
  let count = 0, finish
  const update = changeRefresh(async () => {
    count++
    if (count === 1) await new Promise(resolve => { finish = resolve })
  }, 2)
  update.notify(); update.notify(); update.notify()
  await wait(15)
  assert.equal(count, 1)
  update.notify(); update.notify()
  await wait(10); assert.equal(count, 1)
  finish(); await wait(15)
  assert.equal(count, 2)
  await wait(25); assert.equal(count, 2)
  update.notify(); update.stop()
  await wait(15); assert.equal(count, 2)
})

test('filters unrelated resources, resyncs after reconnect, unsubscribes on leaving', async () => {
  let count = 0
  const stop = refreshOnChanges(['training'], async () => { count++ }, change => change.id === 'current')
  const source = FakeSource.instances.at(-1)
  source.emit('change', { topic: 'exports', id: 'current' })
  source.emit('change', { topic: 'training', id: 'other' })
  await wait(340); assert.equal(count, 0)
  source.emit('change', { topic: 'training', id: 'current' })
  source.emit('change', { topic: 'training', id: 'current' })
  await wait(340); assert.equal(count, 1)
  source.emit('sync')
  await wait(340); assert.equal(count, 2)
  source.emit('change', { topic: 'training', id: 'current' })
  stop(); await wait(340); assert.equal(count, 2)
})
