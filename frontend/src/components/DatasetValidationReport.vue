<script setup lang="ts">
import { computed } from 'vue'
import type { DatasetReport } from '../domain'

const props = defineProps<{ report: DatasetReport }>()
const emit = defineEmits<{ close: []; 'open-image': [imageId: string] }>()
const number = new Intl.NumberFormat('zh-CN')
const metrics = computed(() => props.report.items ?? [])
const issues = computed(() => props.report.issues ?? [])
const hasErrors = computed(() => metrics.value.some(item => item.label === '错误' && Number(item.value) > 0))
</script>

<template>
  <section class="validation-panel" aria-label="运行校验结果" :aria-busy="report.pending">
    <header class="validation-heading">
      <strong class="validation-status" :class="metrics.length ? (hasErrors ? 'error' : 'pass') : undefined" role="status">
        <svg v-if="metrics.length" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor"
          stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="8" cy="8" r="6"/>
          <path v-if="hasErrors" d="m6 6 4 4m0-4-4 4"/>
          <path v-else d="m5 8 2 2 4-4"/>
        </svg>
        {{ report.pending ? '正在校验…' : report.title || '运行校验结果' }}
      </strong>
      <button class="validation-action" type="button" @click="emit('close')">
        收起结果
        <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path d="m4 10 4-4 4 4"/>
        </svg>
      </button>
    </header>

    <template v-if="metrics.length">
      <dl class="validation-metrics">
        <div v-for="item in metrics" :key="item.label" class="validation-metric" :class="{
          error: item.label === '错误' && Number(item.value) > 0,
          warning: item.label === '警告' && Number(item.value) > 0,
        }">
          <dt>{{ item.label }}</dt>
          <dd>{{ typeof item.value === 'number' ? number.format(item.value) : item.value }}</dd>
        </div>
      </dl>

      <section class="validation-details" aria-label="校验问题清单">
        <div class="details-heading">
          <strong>校验问题清单（{{ number.format(issues.length) }}）</strong>
          <span>数据集规则</span>
        </div>
        <ul v-if="issues.length" class="validation-issues">
          <li v-for="(issue, index) in issues" :key="index" class="validation-issue" :class="issue.severity">
            <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor"
              stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"
              role="img" :aria-label="issue.severity === 'error' ? '错误' : '警告'">
              <path v-if="issue.severity === 'warning'" d="M8 2 15 14H1Z"/>
              <circle v-else cx="8" cy="8" r="6.5"/>
              <path d="M8 6v3m0 2.5h.01"/>
            </svg>
            <span>{{ issue.message }}</span>
            <button v-if="issue.image_id" class="validation-action image-link" type="button"
              @click="emit('open-image', issue.image_id)">
              查看图片
              <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
                <path d="M9 3h4v4m0-4L7 9m5 0v4H3V4h4"/>
              </svg>
            </button>
          </li>
        </ul>
        <p v-else class="validation-empty">未发现校验问题。</p>
      </section>
    </template>
    <p v-else-if="report.messages?.length" class="validation-feedback">{{ report.messages.join('；') }}</p>
  </section>
</template>

<style scoped>
.validation-panel {
  padding: 12px; border: 1px solid #d7dfeb; border-radius: 8px;
  background: #f2f5fc; color: var(--text, #364152); font-size: 12px;
}
.validation-heading, .details-heading {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 5px;
}
.validation-status {
  display: inline-flex; align-items: center; gap: 4px; padding: 2px 6px;
  border: 1px solid transparent; border-radius: 3px; font-size: 11px;
}
.validation-status.pass { color: #186432; border-color: #abd4b8; background: #e8f4eb; }
.validation-status.error { color: #a9292f; border-color: #e8b9bd; background: #fff1f2; }
.validation-action {
  display: inline-flex; align-items: center; gap: 3px; flex: none; padding: 3px 0;
  border: 0; background: transparent; color: var(--muted, #5c6775); font: inherit; white-space: nowrap; cursor: pointer;
}
.validation-action:hover { text-decoration: underline; }
.validation-action.image-link { color: var(--primary, #4f6885); }
.validation-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 10px 0 0; }
.validation-metric {
  padding: 8px; border: 1px solid #dce2ea; border-radius: 5px; background: #fff; color: var(--muted, #5c6775);
}
.validation-metric.error { color: #a9292f; background: #fff1f2; border-color: #efb8be; }
.validation-metric.warning { color: #805500; background: #fff6d8; border-color: #eed18b; }
.validation-metric dt { display: flex; justify-content: space-between; align-items: center; gap: 4px; font-size: 11px; }
.validation-metric dt::after { content: ''; width: 6px; height: 6px; flex: none; border-radius: 50%; background: #b6c0cf; }
.validation-metric.error dt::after { background: #c53d46; }
.validation-metric.warning dt::after { background: #db9009; }
.validation-metric dd { margin: 3px 0 0; font: 700 17px/1.2 var(--numeric, monospace); }
.validation-details { margin-top: 10px; padding-top: 7px; border-top: 1px solid #d7dfeb; }
.details-heading strong { font-weight: 600; }
.details-heading span { font-size: 10px; color: var(--muted, #5c6775); }
.validation-issues { display: grid; gap: 6px; padding: 0; margin: 7px 0 0; list-style: none; }
.validation-issue {
  display: flex; align-items: flex-start; gap: 6px; min-width: 0; padding: 7px;
  border: 1px solid #dce2ea; border-radius: 4px; background: #fff;
}
.validation-issue > svg { flex: none; margin-top: 1px; color: #ad6308; }
.validation-issue.error > svg { color: #a9292f; }
.validation-issue > span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.validation-issue .image-link { align-self: center; }
.validation-empty, .validation-feedback { margin: 7px 0 0; color: var(--muted, #5c6775); overflow-wrap: anywhere; }
</style>
