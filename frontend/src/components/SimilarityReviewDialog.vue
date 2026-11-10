<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { annotationStatusLabels } from '../domain'
import type { DatasetImage, SimilarityDecision } from '../domain'

const props = defineProps<{
  datasetName: string
  images: [DatasetImage, DatasetImage]
  fingerprints: [string | null | undefined, string | null | undefined]
  groupIndex: number
  groupCount: number
  reviewable: boolean
  confirmed: boolean
  busy: boolean
  error: string
  feedback: string
  result: string
  refreshing: boolean
  refreshError: string | null
}>()
const emit = defineEmits<{ close: []; refresh: []; step: [offset: -1 | 1]; submit: [decision: SimilarityDecision] }>()
const dialog = ref<HTMLDialogElement>()
const zoom = ref(100)
const loaded = ref([false, false])
const unavailable = ref([false, false])
const choosingDiscard = ref(false)
const discard = ref<'discard_image' | 'discard_related'>()
const sideLabels = ['左图', '右图']
const panes: (HTMLElement | undefined)[] = []
let reflected: HTMLElement | undefined

const ready = computed(() => props.reviewable && loaded.value.every(Boolean) && !props.busy)
const groupKey = computed(() => props.images.map((image, index) => `${image.id}:${props.fingerprints[index] ?? ''}`).join('|'))

watch(groupKey, () => {
  zoom.value = 100
  loaded.value = [false, false]
  unavailable.value = [false, false]
  choosingDiscard.value = false
  discard.value = undefined
  reflected = undefined
})

function imageUrl(image: DatasetImage, index: number) {
  const fingerprint = props.fingerprints[index]
  if (!image.src || !fingerprint) return image.src
  return `${image.src}${image.src.includes('?') ? '&' : '?'}fingerprint=${encodeURIComponent(fingerprint)}`
}

function setPane(index: number, element: unknown) {
  panes[index] = element instanceof HTMLElement ? element : undefined
}

function syncScroll(event: Event, index: number) {
  const source = event.currentTarget as HTMLElement
  const target = panes[1 - index]
  if (source === reflected) {
    reflected = undefined
    return
  }
  if (!target) return
  const left = source.scrollLeft / Math.max(1, source.scrollWidth - source.clientWidth) * (target.scrollWidth - target.clientWidth)
  const top = source.scrollTop / Math.max(1, source.scrollHeight - source.clientHeight) * (target.scrollHeight - target.clientHeight)
  if (Math.abs(left - target.scrollLeft) < 1 && Math.abs(top - target.scrollTop) < 1) return
  reflected = target
  target.scrollTo(left, top)
}

function close() {
  if (!props.busy) emit('close')
}

onMounted(() => dialog.value?.showModal())
</script>

<template>
  <dialog ref="dialog" class="similarity-dialog" aria-labelledby="similarity-heading" closedby="none" @cancel="$event.preventDefault()">
    <header class="review-header">
      <div>
        <h2 id="similarity-heading">{{ confirmed ? '查看已确认重复图' : reviewable ? '重复图人工审核' : '查看对比图' }}</h2>
        <p>{{ datasetName }}</p>
      </div>
      <button class="button" type="button" aria-label="关闭对比图" :disabled="busy" @click="close">关闭</button>
    </header>
    <div class="zoom-tools">
      <label>同步缩放 <input v-model.number="zoom" type="range" min="100" max="300" step="25"></label>
      <output>{{ zoom }}%</output>
      <button class="button" type="button" :disabled="zoom === 100" @click="zoom = 100">重置</button>
      <nav class="pair-navigation" aria-label="图片对切换">
        <button class="button" type="button" :disabled="busy || groupIndex === 0" @click="emit('step', -1)">上一组</button>
        <span aria-live="polite">{{ groupIndex + 1 }} / {{ groupCount }} 组</span>
        <button class="button" type="button" :disabled="busy || groupIndex + 1 >= groupCount" @click="emit('step', 1)">下一组</button>
      </nav>
    </div>
    <div class="comparison-grid">
      <section v-for="(image, index) in images" :key="`${groupKey}:${index}`" class="comparison-image">
        <header>
          <strong :title="image.name">{{ sideLabels[index] }} · {{ image.name }}</strong>
          <span>{{ image.split ?? '未分集' }} · {{ image.width }} × {{ image.height }} · {{ annotationStatusLabels[image.status] }} · {{ image.annotations.length }} 个标注</span>
        </header>
        <div :ref="element => setPane(index, element)" class="image-pane" @scroll.passive="syncScroll($event, index)">
          <div v-if="image.src && !unavailable[index]" class="image-surface" :style="{ width: `${zoom}%`, height: `${zoom}%` }">
            <img :src="imageUrl(image, index)" :alt="`${sideLabels[index]} ${image.name}`" decoding="async"
              @load="loaded[index] = true" @error="unavailable[index] = true; loaded[index] = false">
          </div>
          <p v-else class="preview-empty">图片无法加载</p>
        </div>
      </section>
    </div>
    <p v-if="error" class="review-error" role="alert">{{ error }}</p>
    <p v-if="busy" class="review-status" role="status">正在保存审核…</p>
    <p v-else-if="result" class="review-status" role="status">
      {{ result }}{{ refreshing ? '，正在更新分组…' : !refreshError && groupCount === 1 ? '。暂无其他分组。' : '。' }}
    </p>
    <p v-else-if="feedback" class="review-status" role="status">{{ feedback }}</p>
    <p v-else-if="!reviewable && !confirmed" class="review-status">当前可预览对比图。请在最新的重复图报告中发起审核。</p>
    <p v-if="refreshError" class="review-error" role="alert">
      {{ refreshError }} <button class="button" type="button" @click="emit('refresh')">重试刷新</button>
    </p>
    <fieldset v-if="reviewable && choosingDiscard" class="discard-selection" :disabled="busy">
      <legend>选择要排除的样本</legend>
      <label><input v-model="discard" type="radio" name="discard-side" value="discard_image"> 左图 · {{ images[0].name }}</label>
      <label><input v-model="discard" type="radio" name="discard-side" value="discard_related"> 右图 · {{ images[1].name }}</label>
      <p>排除后样本移出有效数据集，原图和标注可从「已排除样本」恢复。</p>
    </fieldset>
    <footer v-if="reviewable" class="review-actions">
      <template v-if="choosingDiscard">
        <button class="button" type="button" :disabled="busy" @click="choosingDiscard = false; discard = undefined">取消选择</button>
        <button class="button danger" type="button" :disabled="!ready || !discard" @click="discard && emit('submit', discard)">确认排除</button>
      </template>
      <template v-else>
        <button class="button primary" type="button" :disabled="!ready" @click="emit('submit', 'keep_both')">两张都保留</button>
        <button class="button danger" type="button" :disabled="!ready" @click="choosingDiscard = true">丢弃一张</button>
      </template>
    </footer>
  </dialog>
</template>

<style scoped>
.similarity-dialog { width:min(1080px,calc(100% - 32px)); max-height:92vh; padding:16px; overflow:auto; border:1px solid #dce4ee; border-radius:8px; color:#243142; background:#fff; }
.similarity-dialog::backdrop { background:#202e4580; }
.review-header, .zoom-tools, .review-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.review-header { justify-content:space-between; }
.review-header h2 { margin:0; font-size:18px; }
.review-header p, .review-status, .discard-selection p { margin:4px 0; font-size:12px; color:#5c6775; }
.zoom-tools { margin:12px 0 8px; font-size:12px; }
.zoom-tools label { display:flex; align-items:center; gap:6px; }
.pair-navigation { display:flex; align-items:center; gap:8px; margin-left:auto; }
.comparison-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
.comparison-image { min-width:0; border:1px solid #dce4ee; border-radius:5px; overflow:hidden; }
.comparison-image header { display:grid; gap:4px; padding:8px; background:#f4f7fa; }
.comparison-image strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.comparison-image span { color:#5c6775; font-size:11px; }
.image-pane { height:clamp(170px,45vh,520px); overflow:auto; background:#eef2f6; }
.image-surface img { display:block; width:100%; height:100%; object-fit:contain; }
.preview-empty { text-align:center; padding:12px; color:#5c6775; }
.discard-selection { display:grid; gap:5px; margin:10px 0 0; padding:8px; border:1px solid #eed5d5; border-radius:4px; font-size:13px; }
.discard-selection label { overflow-wrap:anywhere; }
.review-actions { justify-content:flex-end; margin-top:12px; }
.review-error { margin:8px 0 0; color:#a32929; font-size:12px; }
</style>
