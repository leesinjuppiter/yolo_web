import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { webcrypto } from 'node:crypto'
import { createUuid } from '../src/utils/id.ts'

const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
afterEach(() => Object.defineProperty(globalThis, 'crypto', descriptor))
const useCrypto = value => Object.defineProperty(globalThis, 'crypto', { configurable: true, value })

test('uses the native UUID API when available', () => {
  const id = '11680975-1c07-4b0a-9237-126c160a4488'
  const crypto = { randomUUID() { assert.equal(this, crypto); return id } }
  useCrypto(crypto)
  assert.equal(createUuid(), id)
})

test('HTTP fallback produces distinct RFC 4122 v4 IDs without randomUUID', () => {
  useCrypto({ getRandomValues: webcrypto.getRandomValues.bind(webcrypto) })
  const ids = Array.from({ length: 1000 }, () => createUuid())
  assert.equal(new Set(ids).size, ids.length)
  for (const id of ids) assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
})

test('reports missing browser cryptography explicitly', () => {
  useCrypto(undefined)
  assert.throws(createUuid, /不支持安全随机数/)
})
