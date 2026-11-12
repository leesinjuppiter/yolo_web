import assert from 'node:assert/strict'
import { test } from 'node:test'
import { validateReport, validateModelReports } from '../src/types/reports.ts'

const independent = () => ({ actualDevice: 'cpu', metrics: { map50: .7 },
  snapshot: { digest: 'frozen', sampleCount: 10 },
  perClass: [{ classIndex: 0, name: '煤', map50_95: .5 }],
  protocolDigest: 'keep-extra-evidence' })
const exported = () => ({ format: 'onnx', environment: { system: 'Linux', machine: 'x86_64', python: '3.12' },
  loadCheck: { status: 'passed' }, benchmark: null,
  validation: { status: 'completed', snapshotDigest: 'frozen', sampleCount: 10,
    baseline: { metrics: { map50: .7 } }, candidate: { metrics: { map50: .69 } }, delta: { map50: -.01 } } })

test('accepts existing independent and paired reports without dropping evidence', () => {
  const report = independent(), before = structuredClone(report)
  validateReport(report)
  assert.deepEqual(report, before)
  validateReport(exported())
  validateReport({ ...exported(), validation: { status: 'insufficient', reason: '没有 test 分集' } })
})

test('rejects malformed nested report fields at the API boundary', () => {
  for (const report of [
    { ...independent(), metrics: { map50: '0.7' } },
    { ...independent(), metrics: { map50: NaN } },
    { ...independent(), snapshot: [] },
    { ...independent(), perClass: [{}] },
    { ...exported(), validation: { status: 'completed', sampleCount: 10, snapshotDigest: 'frozen' } },
    { ...exported(), validation: { status: 'unknown' } },
  ]) assert.throws(() => validateReport(report), /验证报告格式不符合约定/)
})

test('checks reports inside lists, model details, comparisons, and job details', () => {
  const payload = { models: [{ evaluation: { report: independent() }, evaluations: [{ report: null }] }],
    items: [{ report: exported() }], report: null }
  validateModelReports(payload)
  payload.models[0].evaluation.report.metrics.map50 = 'broken'
  assert.throws(() => validateModelReports(payload), /指标必须为有限数值/)
})

test('checks benchmark fields when a paired report includes timings', () => {
  const report = { ...exported(), benchmark: { device: 'cpu', provider: 'CPUExecutionProvider', precision: 'fp32',
    timingScope: 'preprocess through postprocess', latencyAvgMs: 5, latencyP95Ms: 6,
    throughputImagesPerSecond: 200, batchSize: 1, warmup: 3, iterations: 20, inputSize: [1, 3, 640, 640] } }
  validateReport(report)
  report.benchmark.inputSize = ['640']
  assert.throws(() => validateReport(report), /输入尺寸/)
})
