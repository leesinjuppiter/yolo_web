import assert from 'node:assert/strict'
import { test } from 'node:test'
import { PagePreloader } from '../src/startup/preloader.ts'

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const step = (key, load) => ({ key, label: key, load })

test('loads modules in parallel; completion reflects real work, then seeds are consumed once', async () => {
  const a = deferred(), b = deferred(), updates = []
  let started = 0
  const loader = new PagePreloader([
    step('datasets', () => { started++; return a.promise }),
    step('training', () => { started++; return b.promise }),
  ])
  const result = loader.run(states => updates.push(states))
  assert.equal(started, 2)
  assert.equal(updates.at(-1).filter(state => state.status === 'ready').length, 0)
  a.resolve({ id: 'dataset' })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(updates.at(-1).filter(state => state.status === 'ready').length, 1)
  b.resolve({ total: 3 })
  assert.equal(await result, true)
  assert.deepEqual(loader.take('datasets'), { value: { id: 'dataset' }, stale: false })
  assert.equal(loader.take('datasets'), undefined)
  assert.equal(loader.take('training').value.total, 3)
})

test('failed module is retried without repeating successful preload requests', async () => {
  let a = 0, b = 0
  const loader = new PagePreloader([
    step('datasets', async () => { a++; return [] }),
    step('models', async () => { b++; if (b === 1) throw new Error('connection lost'); return { total: 4 } }),
  ])
  assert.equal(await loader.run(() => {}), false)
  assert.equal(loader.states[1].error, 'connection lost')
  assert.equal(await loader.run(() => {}), true)
  assert.equal(a, 1)
  assert.equal(b, 2)
  assert.equal(loader.take('models').value.total, 4)
})

test('changes arriving during and after preload mark unused seeds stale for normal page refresh', async () => {
  const pending = deferred()
  const loader = new PagePreloader([step('training', () => pending.promise), step('models', async () => 2)])
  const result = loader.run(() => {})
  loader.invalidate(['training'])
  pending.resolve(1)
  await result
  loader.invalidate(['models'])
  assert.deepEqual(loader.take('training'), { value: 1, stale: true })
  assert.deepEqual(loader.take('models'), { value: 2, stale: true })
})

test('timeout exits the loading screen even when a loader does not acknowledge abort', async () => {
  const loader = new PagePreloader([step('deployments', () => new Promise(() => {}))], 5)
  assert.equal(await loader.run(() => {}), false)
  assert.equal(loader.states[0].status, 'failed')
  assert.match(loader.states[0].error, /超时/)
})

test('cancel ends in-flight startup and allows a retry', async () => {
  let attempt = 0
  const loader = new PagePreloader([step('datasets', () => ++attempt === 1 ? new Promise(() => {}) : Promise.resolve([]))])
  const pending = loader.run(() => {})
  loader.cancel()
  assert.equal(await pending, false)
  assert.equal(await loader.run(() => {}), true)
})
