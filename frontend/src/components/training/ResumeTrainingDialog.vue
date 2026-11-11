<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { getTrainingOptions, resumeTraining } from '../../api/training'
import type { TrainingOptions, TrainingResumeConfig, TrainingTask } from '../../types/training'
import { createUuid } from '../../utils/id'

const props = defineProps<{ task: TrainingTask }>()
const emit = defineEmits<{ close: []; created: [id: string] }>()
const dialog = ref<HTMLDialogElement>()
const options = ref<TrainingOptions>()
const error = ref('')
const loading = ref(true)
const busy = ref(false)
const request = new AbortController()
let submission: { payload: string; key: string } | undefined
const draft = reactive<TrainingResumeConfig>({
  name: `${props.task.config.name.slice(0, 112)} - 恢复`,
  deviceId: props.task.config.deviceId,
  batchSize: props.task.config.batchSize,
  workers: props.task.config.workers ?? 0,
  amp: props.task.config.amp,
})
const isCuda = computed(() => options.value?.devices.find(device => device.id === draft.deviceId)?.kind === 'cuda')
watch(isCuda, enabled => { if (!enabled) draft.amp = false })

async function loadOptions() {
  loading.value = true
  error.value = ''
  try {
    options.value = await getTrainingOptions(request.signal)
    if (!options.value.devices.some(device => device.id === draft.deviceId)) draft.deviceId = ''
  } catch (cause) {
    if (!request.signal.aborted) error.value = cause instanceof Error ? cause.message : '读取执行设备失败'
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (busy.value || loading.value || !draft.deviceId) return
  error.value = ''
  busy.value = true
  const config = { ...draft, name: draft.name.trim(), amp: isCuda.value && draft.amp }
  const payload = JSON.stringify(config)
  if (submission?.payload !== payload) submission = { payload, key: createUuid() }
  try {
    const task = await resumeTraining(props.task.id, config, submission.key)
    emit('created', task.id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法恢复训练'
  } finally {
    busy.value = false
  }
}

onMounted(() => { dialog.value?.showModal(); void loadOptions() })
onBeforeUnmount(() => request.abort())
</script>

<template>
  <dialog ref="dialog" class="resume-dialog" aria-labelledby="resume-training-title"
    @cancel.prevent="!busy && emit('close')">
    <form @submit.prevent="submit">
      <h2 id="resume-training-title">恢复中断训练</h2>
      <p>创建新的执行记录，沿用原任务的数据快照和训练计划。提交时将检查 last.pt 是否包含完整恢复状态。</p>
      <p class="source">原任务：{{ task.config.name }} · 原计划 {{ task.config.epochs }} 轮</p>
      <p v-if="options?.workerStatus?.reason">{{ options.workerStatus.reason }}</p>
      <fieldset :disabled="busy || loading">
        <label>新任务名称
          <input v-model.trim="draft.name" type="text" maxlength="120" required>
        </label>
        <label>运行设备
          <select v-model="draft.deviceId" required>
            <option value="" disabled>请选择当前可用设备</option>
            <option v-for="device in options?.devices" :key="device.id" :value="device.id">{{ device.name }}</option>
          </select>
        </label>
        <label>批次大小
          <input v-model.number="draft.batchSize" type="number" min="1" max="1024" required>
        </label>
        <label>数据加载进程数
          <input v-model.number="draft.workers" type="number" min="0" max="32" required>
        </label>
        <label class="checkbox"><input v-model="draft.amp" type="checkbox" :disabled="!isCuda">混合精度（仅 CUDA）</label>
      </fieldset>
      <p v-if="loading" role="status">正在读取执行设备…</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <footer>
        <button type="button" class="button" :disabled="busy" @click="emit('close')">返回</button>
        <button v-if="!options && !loading" type="button" class="button" @click="loadOptions">重试读取设备</button>
        <button type="submit" class="button primary" :disabled="busy || loading || !draft.deviceId">
          {{ busy ? '正在校验检查点…' : '校验并创建恢复任务' }}
        </button>
      </footer>
    </form>
  </dialog>
</template>

<style scoped>
.resume-dialog { width: min(600px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); padding: 22px; border: 1px solid var(--line); border-radius: 10px; color: var(--text); background: var(--surface); }
.resume-dialog::backdrop { background: #29344977; }
h2 { margin: 0; font-size: 19px; }
p { color: var(--muted); font-size: 13px; line-height: 1.6; }
.source { padding: 8px; border: 1px solid var(--line); background: var(--soft); overflow-wrap: anywhere; }
fieldset { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; border: 0; margin: 16px 0; padding: 0; }
label { display: grid; gap: 5px; font-size: 13px; }
input:not([type='checkbox']), select { min-width: 0; width: 100%; min-height: 34px; padding: 5px 8px; border: 1px solid var(--line); border-radius: 5px; background: var(--surface); }
.checkbox { display: flex; align-items: center; gap: 6px; }
.error { color: var(--danger); }
footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
@media (max-width: 480px) { fieldset { grid-template-columns: 1fr; } }
</style>
