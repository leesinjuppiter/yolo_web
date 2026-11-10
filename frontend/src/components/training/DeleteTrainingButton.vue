<script setup lang="ts">
import { ref } from 'vue'
import { deleteTraining } from '../../api/training'
import { terminalTrainingStates, type TrainingTask } from '../../types/training'

const props = defineProps<{ task: TrainingTask }>()
const emit = defineEmits<{ deleted: [] }>()
const dialog = ref<HTMLDialogElement>()
const busy = ref(false)
const error = ref('')

function open() {
  error.value = ''
  dialog.value?.showModal()
}

async function confirm() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await deleteTraining(props.task.id)
    dialog.value?.close()
    emit('deleted')
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '删除训练记录失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <template v-if="terminalTrainingStates.has(task.status)">
    <button type="button" class="button danger" :disabled="!!task.modelVersion"
      :title="task.modelVersion ? '已注册模型版本，需保留来源记录' : undefined" @click="open">删除记录</button>
    <dialog ref="dialog" class="delete-dialog" aria-label="确认删除训练记录"
      @cancel.prevent="!busy && dialog?.close()">
      <form @submit.prevent="confirm">
        <h2>删除训练记录「{{ task.config.name }}」？</h2>
        <p>任务、日志和指标记录将永久删除。磁盘上的训练文件会保留。</p>
        <p v-if="error" class="delete-error" role="alert">{{ error }}</p>
        <div class="delete-actions">
          <button type="button" class="button" :disabled="busy" autofocus @click="dialog?.close()">取消</button>
          <button type="submit" class="button danger" :disabled="busy">{{ busy ? '正在删除…' : '确认删除' }}</button>
        </div>
      </form>
    </dialog>
  </template>
</template>

<style scoped>
.delete-dialog { width: min(460px, calc(100vw - 32px)); padding: 20px; border: 1px solid var(--line); border-radius: 10px; color: var(--text); background: var(--surface); }
.delete-dialog::backdrop { background: #29344977; }
h2 { font-size: 17px; margin: 0; overflow-wrap: anywhere; }
p { margin: 10px 0; color: var(--muted); white-space: normal; }
.delete-error { color: var(--danger); }
.delete-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
</style>
