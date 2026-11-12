import assert from 'node:assert/strict'
import { test } from 'node:test'
import { AnnotationImageCache, nearbyImages, thumbnailUrl } from '../src/annotation/image-cache.ts'

class FakeImage {
  static images = []
  constructor() { FakeImage.images.push(this) }
  decode() { return Promise.resolve() }
}
globalThis.Image = FakeImage

test('foreground and background share one download and retain the decoded image', async () => {
  const cache = new AnnotationImageCache()
  const background = cache.load('/one', 'low')
  const foreground = cache.load('/one', 'high')
  assert.equal(foreground, background)
  const image = FakeImage.images.at(-1)
  assert.equal(image.fetchPriority, 'high')
  assert.equal(cache.ready('/one'), undefined)
  await image.onload()
  assert.equal(await foreground, image)
  assert.equal(cache.ready('/one'), image)
  const before = FakeImage.images.length
  assert.equal(await cache.load('/one'), image)
  assert.equal(FakeImage.images.length, before)
  cache.clear()
  assert.equal(cache.ready('/one'), undefined)
})

test('leaving the nearby window cancels an obsolete download; it can be requested again', async () => {
  const cache = new AnnotationImageCache()
  const loading = cache.load('/old')
  const cancelled = assert.rejects(loading, { name: 'AbortError' })
  const image = FakeImage.images.at(-1)
  cache.retain(['/new'])
  await cancelled
  assert.equal(image.src, '')
  assert.equal(image.onload, null)
  const next = cache.load('/old')
  await FakeImage.images.at(-1).onload()
  await next
  assert.notEqual(FakeImage.images.at(-1), image)
})

test('failed download or decode is removed so retry can succeed', async () => {
  const cache = new AnnotationImageCache()
  const first = cache.load('/retry')
  FakeImage.images.at(-1).onerror()
  await assert.rejects(first, /加载失败/)
  const second = cache.load('/retry')
  const image = FakeImage.images.at(-1)
  image.decode = () => Promise.reject(new Error('bad image'))
  await image.onload()
  await assert.rejects(second, /加载失败/)
  const third = cache.load('/retry')
  await FakeImage.images.at(-1).onload()
  assert.equal(await third, cache.ready('/retry'))
})

test('keeps the current and next/previous images within a decoded memory budget', () => {
  const images = Array.from({ length: 5 }, (_, i) => ({ src: String(i), width: 4096, height: 2168 }))
  assert.deepEqual(nearbyImages(images, 2).map(item => item.src), ['2', '3', '1'])
  images[2].width = 10000; images[2].height = 4000
  assert.deepEqual(nearbyImages(images, 2).map(item => item.src), ['2'])
  assert.deepEqual(nearbyImages(images, -1), [])
  assert.deepEqual(nearbyImages([{ width: 1, height: 1 }], 0), [])
})

test('thumbnail URL never replaces the original annotation image URL', () => {
  const original = '/api/datasets/one/images/two/content'
  assert.equal(thumbnailUrl(original), '/api/datasets/one/images/two/thumbnail')
  assert.equal(original, '/api/datasets/one/images/two/content')
  assert.equal(thumbnailUrl('images/demo.jpg'), 'images/demo.jpg')
})
