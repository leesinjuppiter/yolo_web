<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listExcludedImages, restoreExcludedImage } from '../api/datasets'
import { annotationStatusLabels } from '../domain'
import type { Dataset, DatasetImage } from '../domain'

const props = defineProps<{ dataset: Dataset }>()
const emit = defineEmits<{ close: []; restored: [image: DatasetImage] }>()
const dialog = ref<HTMLDialogElement>()
const images = ref<DatasetImage[]>([])
const loading = ref(true)
const restoring = ref('')
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    images.value = await listExcludedImages(props.dataset.id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法读取已排除样本，请重试。'
  } finally {
    loading.value = false
  }
}

async function restore(image: DatasetImage) {
  if (restoring.value) return
  restoring.value = image.id
  error.value = ''
  try {
    const restored = await restoreExcludedImage(props.dataset.id, image.id)
    images.value = images.value.filter(item => item.id !== image.id)
    emit('restored', restored)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法恢复样本，请重试。'
  } finally {
    restoring.value = ''
  }
}

function close() {
  if (!restoring.value) emit('close')
}

onMounted(() => {
  dialog.value?.showModal()
  void load()
})
</script>

<template>
  <dialog ref="dialog" class="excluded-dialog" aria-labelledby="excluded-heading" @cancel.prevent="close">
    <header>
      <div>
        <h2 id="excluded-heading">已排除样本</h2>
        <p>{{ dataset.name }} · 恢复后将重新参与标注、分集和导出。</p>
      </div>
      <button class="button" type="button" aria-label="关闭已排除样本" :disabled="!!restoring" @click="close">关闭</button>
    </header>
    <p v-if="loading" role="status">正在读取已排除样本…</p>
    <div v-else-if="error" class="excluded-error" role="alert">
      {{ error }} <button class="button" type="button" @click="load">重新读取</button>
    </div>
    <p v-else-if="!images.length" class="excluded-empty">当前数据集暂无已排除的图片。</p>
    <ul v-if="images.length" class="excluded-list">
      <li v-for="image in images" :key="image.id">
        <a v-if="image.src" :href="image.src" target="_blank" rel="noopener" :aria-label="`查看原图 ${image.name}`">
          <img :src="image.src" alt="" loading="lazy">
        </a>
        <div class="excluded-meta">
          <strong :title="image.name">{{ image.name }}</strong>
          <span>{{ image.split ?? '未分集' }} · {{ image.width }} × {{ image.height }} · {{ annotationStatusLabels[image.status] }} · {{ image.annotations.length }} 个标注</span>
        </div>
        <button class="button" type="button" :aria-label="`恢复 ${image.name}`" :disabled="!!restoring" @click="restore(image)">
          {{ restoring === image.id ? '恢复中…' : '恢复' }}
        </button>
      </li>
    </ul>
  </dialog>
</template>

<style scoped>
.excluded-dialog { width:min(660px,calc(100% - 32px)); max-height:90vh; padding:16px; border:1px solid #dce4ee; border-radius:8px; color:#243142; background:#fff; }
.excluded-dialog::backdrop { background:#202e4580; }
.excluded-dialog header { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.excluded-dialog h2 { margin:0; font-size:18px; }
.excluded-dialog p { margin:6px 0; color:#5c6775; font-size:12px; }
.excluded-list { display:grid; gap:5px; padding:0; margin:10px 0 0; list-style:none; }
.excluded-list li { display:flex; gap:8px; align-items:center; padding:6px; border:1px solid #dce4ee; border-radius:4px; }
.excluded-list img { display:block; width:58px; height:40px; object-fit:contain; background:#eef2f6; }
.excluded-meta { min-width:0; flex:1; display:grid; gap:4px; }
.excluded-meta strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.excluded-meta span { color:#5c6775; font-size:11px; }
.excluded-error { margin-top:10px; color:#a32929; font-size:12px; }
</style>
