<script setup lang="ts">
import { computed } from 'vue'
import { formatValue } from '../../types/models'
import type { ModelReport,Metrics } from '../../types/reports'
const props=defineProps<{report:ModelReport}>()
const paired=computed(()=>props.report.format==='onnx'?props.report:undefined)
const validation=computed(()=>paired.value?.validation)
const comparison=computed(()=>validation.value?.status==='completed'?validation.value:undefined)
const baseline=computed<Metrics>(()=>comparison.value?.baseline.metrics??{})
const candidate=computed<Metrics>(()=>comparison.value?.candidate.metrics??{})
const metrics=computed<Metrics>(()=>props.report.format==='onnx'?baseline.value:props.report.metrics)
const benchmark=computed(()=>paired.value?.benchmark)
const environment=computed(()=>paired.value?.environment)
const sampleCount=computed(()=>props.report.format==='onnx'?comparison.value?.sampleCount:props.report.snapshot.sampleCount)
const snapshotDigest=computed(()=>props.report.format==='onnx'?comparison.value?.snapshotDigest:props.report.snapshot.digest)
const actualDevice=computed(()=>props.report.format==='onnx'?benchmark.value?.device:props.report.actualDevice)
const metricsKeys=computed(()=>Object.keys(metrics.value))
const percent=(value:number|undefined)=>value===undefined?'—':formatValue(value*100)+' pp'
const perClass=computed(()=>props.report.format==='onnx'?[]:props.report.perClass)
</script>
<template>
 <div class="model-report">
  <p class="model-note">{{report.notice||'报告记录加载、精度对照与性能测试结果。尚未配置业务门槛，质量放行需结合具体用途判断。'}}</p>
  <dl class="model-facts"><div><dt>验证类型</dt><dd>{{paired?'PT / ONNX 配对验证':'独立测试评估'}}</dd></div><div><dt>评估样本</dt><dd>{{sampleCount??'—'}} · test 分集</dd></div><div><dt>执行设备</dt><dd>{{actualDevice??'—'}}</dd></div><div><dt>配对验证</dt><dd>{{validation?.status==='completed'?'已完成':validation?.status==='insufficient'?'数据不足':'见独立评估结果'}}<span v-if="validation?.status==='insufficient'&&validation.reason"> · {{validation.reason}}</span></dd></div><div v-if="paired"><dt>模型加载检查</dt><dd>{{paired.loadCheck.status==='passed'?'通过':'见详细报告'}}</dd></div><div><dt>评估数据摘要</dt><dd class="model-mono">{{snapshotDigest??'—'}}</dd></div></dl>
  <div v-if="metricsKeys.length" class="model-table-scroll"><table class="model-table" style="min-width:540px"><thead><tr><th>精度指标（比例 0–1）</th><th>{{paired?'PT 基准':'实测值'}}</th><th v-if="paired">ONNX FP32</th><th v-if="paired">变化（百分点）</th></tr></thead><tbody><tr v-for="key in metricsKeys" :key="key"><th>{{key}}</th><td>{{formatValue(metrics[key])}}</td><td v-if="paired">{{formatValue(candidate[key])}}</td><td v-if="paired">{{percent(comparison?.delta[key])}}</td></tr></tbody></table></div>
  <template v-if="benchmark"><h4>推理性能</h4><div class="model-metric-grid"><div><span>平均延迟</span><strong>{{formatValue(benchmark.latencyAvgMs)}} ms</strong></div><div><span>P95 延迟</span><strong>{{formatValue(benchmark.latencyP95Ms)}} ms</strong></div><div><span>实测吞吐</span><strong>{{formatValue(benchmark.throughputImagesPerSecond)}} 张/秒</strong></div></div><dl class="model-facts"><div><dt>运行后端 / 精度</dt><dd>{{benchmark.provider}} / {{benchmark.precision}}</dd></div><div><dt>批大小 / 预热 / 次数</dt><dd>{{benchmark.batchSize}} / {{benchmark.warmup}} / {{benchmark.iterations}}</dd></div><div><dt>输入尺寸</dt><dd>{{benchmark.inputSize}}</dd></div><div><dt>计时范围</dt><dd>{{benchmark.timingScope}}</dd></div></dl></template>
  <template v-if="perClass.length"><h4>逐类指标</h4><div class="model-metric-grid"><div v-for="item in perClass" :key="String(item.classIndex)"><span>{{item.name}}</span><strong>{{formatValue(item.map50_95)}}</strong><small>mAP50–95</small></div></div></template>
  <p v-if="environment" class="model-muted">验证环境：{{environment.system}} / {{environment.machine}} / Python {{environment.python}}</p>
  <details><summary>完整报告字段</summary><pre class="model-json">{{JSON.stringify(report,null,2)}}</pre></details>
 </div>
</template>
