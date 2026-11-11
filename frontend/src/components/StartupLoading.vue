<script setup lang="ts">
import { computed } from 'vue'
import type { StepState } from '../startup/preloader'
const props = defineProps<{ steps: StepState[]; running: boolean }>()
defineEmits<{ retry: [] }>()
const completed = computed(() => props.steps.filter(step => step.status === 'ready').length)
const percent = computed(() => Math.round(completed.value / props.steps.length * 100))
const failed = computed(() => props.steps.some(step => step.status === 'failed'))
const labels = { waiting: '等待加载', loading: '正在加载页面与数据', ready: '已就绪', failed: '加载失败' }
</script>
<template>
  <main class="startup-screen" aria-labelledby="startup-title" :aria-busy="running">
    <section class="startup-card">
      <div class="startup-brand">OPTI-METRIX <span>检测系统工作台</span></div>
      <h1 id="startup-title">{{ running || !failed ? '正在加载系统页面' : '部分页面加载未完成' }}</h1>
      <p class="startup-description">正在准备数据集、模型训练、模型仓库和部署中心，完成后进入工作台。</p>
      <div class="startup-progress-label" role="status"><span>已完成 {{ completed }} / {{ steps.length }} 个模块</span><strong>{{ percent }}%</strong></div>
      <progress class="startup-progress" :value="completed" :max="steps.length" aria-label="系统页面加载进度"/>
      <ul class="startup-steps">
        <li v-for="step in steps" :key="step.key" :class="step.status">
          <span class="startup-step-dot" aria-hidden="true"></span>
          <div><strong>{{ step.label }}</strong><p v-if="step.error" role="alert">{{ step.error }}</p></div>
          <span class="startup-step-state">{{ labels[step.status] }}</span>
        </li>
      </ul>
      <button v-if="failed && !running" class="button primary" type="button" @click="$emit('retry')">重试未完成的模块</button>
      <p class="startup-hint">进度按实际完成的模块计算。首次加载时间取决于数据量与网络速度。</p>
    </section>
  </main>
</template>
<style scoped>
.startup-screen { min-height: 100dvh; display: grid; place-items: center; padding: 24px; background: #f5f7fa; color: #26394c; }
.startup-card { width: min(100%, 560px); padding: 36px; border: 1px solid #dce3eb; border-radius: 14px; background: #fff; box-shadow: 0 8px 30px #24374c08; }
.startup-brand { display: flex; align-items: center; gap: 12px; margin-bottom: 30px; font-size: 12px; font-weight: 700; letter-spacing: .06em; color: #4f6b86; }
.startup-brand span { padding-left: 12px; border-left: 1px solid #dce3eb; letter-spacing: 0; color: #64748b; }
h1 { margin: 0 0 12px; font-size: 24px; }
.startup-description, .startup-hint { color: #64748b; font-size: 13px; line-height: 1.8; }
.startup-progress-label { display: flex; justify-content: space-between; margin-top: 26px; font-size: 13px; }
.startup-progress-label strong { font-variant-numeric: tabular-nums; }
.startup-progress { width: 100%; height: 8px; margin: 10px 0 18px; border: 0; border-radius: 8px; overflow: hidden; appearance: none; background: #e8eef5; }
.startup-progress::-webkit-progress-bar { background: #e8eef5; }
.startup-progress::-webkit-progress-value { background: #4f6b86; }
.startup-progress::-moz-progress-bar { background: #4f6b86; }
.startup-steps { padding: 0; margin: 0; list-style: none; }
.startup-steps li { display: flex; align-items: center; gap: 12px; min-height: 56px; border-bottom: 1px solid #edf1f5; font-size: 13px; }
.startup-steps li > div { flex: 1; min-width: 0; }
.startup-steps p { margin: 6px 0; color: #a43838; overflow-wrap: anywhere; }
.startup-step-dot { flex: none; width: 8px; height: 8px; border: 1px solid #b9c6d3; border-radius: 50%; }
.ready .startup-step-dot { background: #40826d; border-color: #40826d; }
.loading .startup-step-dot { background: #4f6b86; border-color: #4f6b86; }
.failed .startup-step-dot { background: #a43838; border-color: #a43838; }
.startup-step-state { flex: none; color: #64748b; font-size: 12px; }
.ready .startup-step-state { color: #40826d; }
.failed .startup-step-state { color: #a43838; }
.startup-hint { margin: 22px 0 0; font-size: 12px; }
.button { margin-top: 20px; }
@media (max-width: 520px) { .startup-screen { padding: 16px; } .startup-card { padding: 24px 20px; } .startup-step-state { max-width: 120px; text-align: right; } }
</style>
