<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { prepareActiveTraining } from '../../api/active-learning'
import type { Iteration, Preflight, TrainingInput } from '../../types/active-learning'
const props = defineProps<{ iteration: Iteration }>()
const emit = defineEmits<{ close: []; train: [value: TrainingInput] }>()
const dialog = ref<HTMLDialogElement>(), report = ref<Preflight>(), error = ref(''), loading = ref(false)
async function check() {
  loading.value = true; error.value = ''; report.value = undefined
  try { report.value = await prepareActiveTraining(props.iteration.id) }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '预检失败' }
  finally { loading.value = false }
}
function proceed() {
  const result = report.value
  if (!result?.ready || !result.manifestId || !result.manifestDigest) return
  emit('train', { iterationId: props.iteration.id, manifestId: result.manifestId, manifestDigest: result.manifestDigest,
    datasetId: props.iteration.datasetId, modelId: 'version:' + props.iteration.baselineVersionId, task: props.iteration.taskType })
}
onMounted(() => { dialog.value?.showModal(); void check() })
</script>
<template>
  <dialog ref="dialog" class="al-dialog" aria-labelledby="al-preflight-title" @cancel.prevent="emit('close')">
    <header><div><h2 id="al-preflight-title">准备下一轮训练</h2><p>{{ iteration.name }} · 核对复核结果与固定训练输入</p></div><button class="button" @click="emit('close')">关闭</button></header>
    <div class="al-dialog-content">
      <p v-if="loading" role="status">正在核对标注版本、分集与文件完整性…</p>
      <p v-if="error" class="al-error" role="alert">{{ error }} <button class="button" @click="check">重试</button></p>
      <template v-if="report">
        <div class="al-stats"><div v-for="(count, key) in report.counts" :key="key"><span>{{ ({ original: '原训练图片', new: '新增图片', revised: '修订图片', unchanged: '复核未改动', total: '合并训练总数', excluded: '重复排除' } as Record<string,string>)[key] ?? key }}</span><strong>{{ count }}</strong></div></div>
        <ul class="al-checks"><li v-for="item in report.checks" :key="item.code" :class="{failed: !item.passed}"><strong>{{ item.passed ? '通过' : '需处理' }} · {{ item.label }}</strong><p v-if="item.message">{{ item.message }}</p></li></ul>
        <p v-for="(item, index) in report.issues" :key="index" class="al-error">{{ item.message }} <span v-if="item.imageId">图片：{{ item.imageId }}</span></p>
        <p v-if="report.manifestDigest" class="al-note">固定清单：<code>{{ report.manifestDigest }}</code></p>
        <p class="al-note">原训练集与已复核新增/修订合并，固定 val/test 不变。下一步进入现有训练配置，需再次确认参数并提交。</p>
      </template>
    </div>
    <footer><button class="button" @click="emit('close')">返回复核</button><button class="button primary" :disabled="loading || !report?.ready" @click="proceed">进入训练配置</button></footer>
  </dialog>
</template>
