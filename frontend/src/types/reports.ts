export type Metrics = Record<string, number>
export interface Benchmark {
  device: string; provider: string; precision: string; timingScope: string
  latencyAvgMs: number; latencyP95Ms: number; throughputImagesPerSecond: number
  batchSize: number; warmup: number; iterations: number; inputSize: number[]
}
export interface IndependentReport {
  format?: undefined
  notice?: string
  actualDevice: string
  metrics: Metrics
  purpose?: 'diagnostic' | 'final'
  snapshot: { digest: string; sampleCount: number; split?: 'val' | 'test' }
  perClass: { classIndex: number; name: string; map50_95: number; maskMap50_95?: number; maskMap50?: number; maskPrecision?: number; maskRecall?: number }[]
}
export interface PairedValidation {
  status: 'completed'; sampleCount: number; snapshotDigest: string
  baseline: { metrics: Metrics }; candidate: { metrics: Metrics }; delta: Metrics
}
export interface ExportReport {
  format: 'onnx'
  notice?: string
  environment: { system: string; machine: string; python: string }
  loadCheck: { status: string }
  validation: PairedValidation | { status: 'insufficient'; reason?: string | null }
  benchmark: Benchmark | null
}
export type ModelReport = IndependentReport | ExportReport

function fields(value: unknown, strings: string[] = [], numbers: string[] = []): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('验证报告格式不符合约定：应为对象')
  const result = value as Record<string, unknown>
  const invalid = strings.find(key => typeof result[key] !== 'string')
    ?? numbers.find(key => typeof result[key] !== 'number' || !Number.isFinite(result[key]))
  if (invalid) throw new Error(`验证报告格式不符合约定：${invalid}`)
  return result
}

function metrics(value: unknown): void {
  if (Object.values(fields(value)).some(item => typeof item !== 'number' || !Number.isFinite(item))) {
    throw new Error('验证报告格式不符合约定：指标必须为有限数值')
  }
}

export function validateReport(value: unknown): asserts value is ModelReport {
  const report = fields(value)
  if (report.notice !== undefined && typeof report.notice !== 'string') throw new Error('验证报告格式不符合约定：notice')
  if (report.format === undefined) {
    fields(report, ['actualDevice'])
    metrics(report.metrics)
    fields(report.snapshot, ['digest'], ['sampleCount'])
    if (!Array.isArray(report.perClass)) throw new Error('验证报告格式不符合约定：perClass')
    report.perClass.forEach(item => fields(item, ['name'], ['classIndex', 'map50_95']))
    report.perClass.forEach(item => {
      for (const key of ['maskMap50_95', 'maskMap50', 'maskPrecision', 'maskRecall']) {
        if (item[key] !== undefined && (typeof item[key] !== 'number' || !Number.isFinite(item[key]))) throw new Error(`验证报告格式不符合约定：${key}`)
      }
    })
    return
  }
  if (report.format !== 'onnx') throw new Error('验证报告格式不符合约定：导出格式')
  fields(report.environment, ['system', 'machine', 'python'])
  fields(report.loadCheck, ['status'])
  const validation = fields(report.validation, ['status'])
  if (validation.status === 'completed') {
    fields(validation, ['snapshotDigest'], ['sampleCount'])
    metrics(fields(validation.baseline).metrics)
    metrics(fields(validation.candidate).metrics)
    metrics(validation.delta)
  } else if (validation.status !== 'insufficient' || (validation.reason != null && typeof validation.reason !== 'string')) {
    throw new Error('验证报告格式不符合约定：验证状态')
  }
  if (report.benchmark !== null) {
    const benchmark = fields(report.benchmark, ['device', 'provider', 'precision', 'timingScope'],
      ['latencyAvgMs', 'latencyP95Ms', 'throughputImagesPerSecond', 'batchSize', 'warmup', 'iterations'])
    if (!Array.isArray(benchmark.inputSize) || benchmark.inputSize.some(item => typeof item !== 'number' || !Number.isFinite(item))) {
      throw new Error('验证报告格式不符合约定：输入尺寸')
    }
  }
}

// These are the report containers returned by model, evaluation, export, and package APIs.
export function validateModelReports(value: unknown): void {
  const payload = fields(value)
  if (payload.report != null) validateReport(payload.report)
  if (payload.evaluation != null) validateModelReports(payload.evaluation)
  for (const key of ['items', 'models', 'evaluations']) {
    if (payload[key] === undefined) continue
    if (!Array.isArray(payload[key])) throw new Error(`验证报告格式不符合约定：${key}`)
    payload[key].forEach(validateModelReports)
  }
}
