<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { TrainingPreview } from '../../types/training'

const props = defineProps<{ previews: TrainingPreview[] }>()
const index = ref(0)
const showLabels = ref(true)
const imageFailed = ref(false)
const preview = computed(() => props.previews[Math.min(index.value, props.previews.length - 1)])
const labelUrl = computed(() => showLabels.value ? preview.value?.groundTruthUrl : undefined)
const imageUrl = computed(() => labelUrl.value || preview.value?.url)
watch(() => props.previews.length, length => { index.value = Math.min(index.value, Math.max(0, length - 1)) })
watch(imageUrl, () => { imageFailed.value = false })

function changePreview(offset: number) {
  index.value += offset
  showLabels.value = true
}
</script>

<template>
  <section class="prediction" aria-labelledby="training-preview-title">
    <header>
      <h2 id="training-preview-title">验证集预测预览</h2>
      <small v-if="preview" :title="preview.name">{{ preview.name }}</small>
    </header>
    <div class="preview-image">
      <img v-if="imageUrl && !imageFailed" :key="imageUrl" :src="imageUrl"
        :alt="`${preview?.name} ${labelUrl ? '真实标注' : '模型预测'}`" @error="imageFailed = true">
      <div v-else class="preview-empty">
        <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="2"/><path d="m3 17 5-4 4 3 4-5 5 5"/>
        </svg>
        <strong>{{ imageFailed ? '图片加载失败' : '暂无验证批次图片' }}</strong>
        <span>{{ imageFailed ? '可以切换查看标注或预测。' : '任务生成验证集预览后会在这里展示。' }}</span>
      </div>
    </div>
    <footer v-if="preview">
      <button class="button" type="button" :disabled="index === 0" @click="changePreview(-1)">上一张</button>
      <button class="button" type="button" :disabled="index >= previews.length - 1" @click="changePreview(1)">下一张</button>
      <span>{{ index + 1 }} / {{ previews.length }}</span>
      <span v-if="preview.width && preview.height">{{ preview.width }} × {{ preview.height }}</span>
      <button v-if="preview.groundTruthUrl" class="button" type="button" :aria-pressed="showLabels" @click="showLabels = !showLabels">
        {{ showLabels ? '显示预测' : '显示真实标注' }}
      </button>
    </footer>
  </section>
</template>

<style scoped>
.prediction { display: flex; flex-direction: column; min-width: 0; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); }
header, footer { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; padding: 11px 13px; }
header { justify-content: space-between; border-bottom: 1px solid var(--line); }
h2 { margin: 0; font-size: 14px; }
small, footer span { font-size: 12px; color: var(--muted); }
small { overflow: hidden; max-width: 100%; text-overflow: ellipsis; white-space: nowrap; }
.preview-image { flex: 1; display: grid; min-height: 230px; padding: 12px; place-items: center; background: var(--soft); border-radius: 0 0 9px 9px; }
.preview-image img { display: block; max-width: 100%; max-height: 470px; object-fit: contain; }
.preview-empty { display: grid; justify-items: center; gap: 8px; padding: 14px; color: var(--muted); text-align: center; font-size: 12px; }
.preview-empty svg { color: #8498b0; }
.preview-empty strong { color: var(--text); }
footer { border-top: 1px solid var(--line); }
.button { min-height: 26px; padding: 4px 8px; font-size: 12px; }
</style>
