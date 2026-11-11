<script setup lang="ts">
import { computed } from 'vue'
import { formatValue } from '../../types/models'
const props=defineProps<{report:Record<string,unknown>}>()
const record=(value:unknown):Record<string,unknown>=>value&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:{}
const validation=computed(()=>record(props.report.validation))
const baseline=computed(()=>record(record(validation.value.baseline).metrics))
const candidate=computed(()=>record(record(validation.value.candidate).metrics))
const metrics=computed(()=>record(props.report.metrics))
const benchmark=computed(()=>record(props.report.benchmark))
const protocol=computed(()=>record(props.report.protocol))
const environment=computed(()=>record(props.report.environment))
const snapshot=computed(()=>record(props.report.snapshot))
const metricsKeys=computed(()=>Object.keys(baseline.value).length?Object.keys(baseline.value):Object.keys(metrics.value))
const percent=(value:unknown)=>typeof value==='number'?formatValue(value*100)+' pp':'—'
const perClass=computed(()=>Array.isArray(props.report.perClass)?props.report.perClass.map(record):[])
</script>
<template>
 <div class="model-report">
  <p class="model-note">{{report.notice||'报告记录加载、精度对照与性能测试结果。尚未配置业务门槛，质量放行需结合具体用途判断。'}}</p>
  <dl class="model-facts"><div><dt>验证类型</dt><dd>{{report.format?'PT / ONNX 配对验证':'独立测试评估'}}</dd></div><div><dt>评估样本</dt><dd>{{validation.sampleCount??snapshot.sampleCount??'—'}} · test 分集</dd></div><div><dt>执行设备</dt><dd>{{report.actualDevice??benchmark.device??'—'}}</dd></div><div><dt>配对验证</dt><dd>{{validation.status==='completed'?'已完成':validation.status==='insufficient'?'数据不足':'见独立评估结果'}}<span v-if="validation.reason"> · {{validation.reason}}</span></dd></div><div v-if="report.loadCheck"><dt>模型加载检查</dt><dd>{{record(report.loadCheck).status==='passed'?'通过':'见详细报告'}}</dd></div><div><dt>评估数据摘要</dt><dd class="model-mono">{{validation.snapshotDigest??snapshot.digest??protocol.snapshotDigest??'—'}}</dd></div></dl>
  <div v-if="metricsKeys.length" class="model-table-scroll"><table class="model-table" style="min-width:540px"><thead><tr><th>精度指标（比例 0–1）</th><th>{{report.format?'PT 基准':'实测值'}}</th><th v-if="report.format">ONNX FP32</th><th v-if="report.format">变化（百分点）</th></tr></thead><tbody><tr v-for="key in metricsKeys" :key="key"><th>{{key}}</th><td>{{formatValue(report.format?baseline[key]:metrics[key])}}</td><td v-if="report.format">{{formatValue(candidate[key])}}</td><td v-if="report.format">{{percent(record(validation.delta)[key])}}</td></tr></tbody></table></div>
  <template v-if="Object.keys(benchmark).length"><h4>推理性能</h4><div class="model-metric-grid"><div><span>平均延迟</span><strong>{{formatValue(benchmark.latencyAvgMs)}} ms</strong></div><div><span>P95 延迟</span><strong>{{formatValue(benchmark.latencyP95Ms)}} ms</strong></div><div><span>实测吞吐</span><strong>{{formatValue(benchmark.throughputImagesPerSecond)}} 张/秒</strong></div></div><dl class="model-facts"><div><dt>运行后端 / 精度</dt><dd>{{benchmark.provider}} / {{benchmark.precision}}</dd></div><div><dt>批大小 / 预热 / 次数</dt><dd>{{benchmark.batchSize}} / {{benchmark.warmup}} / {{benchmark.iterations}}</dd></div><div><dt>输入尺寸</dt><dd>{{benchmark.inputSize}}</dd></div><div><dt>计时范围</dt><dd>{{benchmark.timingScope}}</dd></div></dl></template>
  <template v-if="perClass.length"><h4>逐类指标</h4><div class="model-metric-grid"><div v-for="item in perClass" :key="String(item.classIndex)"><span>{{item.name}}</span><strong>{{formatValue(item.map50_95)}}</strong><small>mAP50–95</small></div></div></template>
  <p v-if="Object.keys(environment).length" class="model-muted">验证环境：{{environment.system}} / {{environment.machine}} / Python {{environment.python}}</p>
  <details><summary>完整报告字段</summary><pre class="model-json">{{JSON.stringify(report,null,2)}}</pre></details>
 </div>
</template>
