<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { activeOptions, createActiveTask, createIteration, createValDiagnostic } from '../../api/active-learning'
import { taskLabels } from '../../domain'
import { createUuid } from '../../utils/id'
import { strategyLabels } from '../../types/active-learning'
import type { ActiveOptions, Iteration, Strategy, TaskConfig } from '../../types/active-learning'
const props = defineProps<{ iterations: Iteration[]; iteration?: Iteration }>()
const emit = defineEmits<{ close: []; created: [taskId: string] }>()
const dialog = ref<HTMLDialogElement>(), options = ref<ActiveOptions>(), error = ref(''), busy = ref(false)
const notice = ref('')
const existing = ref(props.iteration?.id ?? ''), name = ref(''), goal = ref(''), modelId = ref(''), datasetId = ref('')
const config = reactive<TaskConfig>({ iterationId: '', strategy: 'mixed', deviceId: 'cpu', imageSize: 640,
  retainConfidence: .05, minConfidence: .05, maxConfidence: .5, nmsIou: .7,
  referenceLimit: 50, candidateLimit: 50, includeNoPredictions: false })
const strategies: { value: Strategy; description: string }[] = [
  { value: 'error_first', description: '先查看已暴露的问题，指导修正或现场补采' },
  { value: 'low_confidence', description: '从未标注图片中筛选低置信度预测' },
  { value: 'mixed', description: '同时提供问题参考和未标注候选' },
]
const selectedIteration = computed(() => props.iterations.find(item => item.id === existing.value) ?? props.iteration)
const model = computed(() => options.value?.models.find(item => item.id === (selectedIteration.value?.baselineVersionId ?? modelId.value)))
const datasets = computed(() => options.value?.datasets.filter(item => item.id === model.value?.datasetId) ?? [])
const evaluations = computed(() => options.value?.evaluations.filter(item => item.versionId === model.value?.id && item.status === 'succeeded' && item.purpose === 'diagnostic') ?? [])
let taskKey = createUuid(), createdIteration: Iteration | undefined
async function load() {
  error.value = ''
  try { options.value = await activeOptions() }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '选项加载失败' }
}
async function submit() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const iteration = selectedIteration.value ?? createdIteration ?? await createIteration({ name: name.value.trim(), goal: goal.value,
      baselineVersionId: modelId.value, datasetId: datasetId.value || datasets.value[0]?.id || '' })
    createdIteration = iteration
    const task = await createActiveTask({ ...config, iterationId: iteration.id,
      evaluationId: config.strategy === 'low_confidence' ? undefined : config.evaluationId }, taskKey)
    taskKey = createUuid(); emit('created', task.id)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '创建推荐任务失败' }
  finally { busy.value = false }
}
async function diagnose() {
  if(!model.value)return
  busy.value=true;error.value=''
  try {
    const result=await createValDiagnostic(model.value.id,selectedIteration.value?.sourceTaskId ?? model.value.sourceTaskId,config.imageSize,createUuid())
    notice.value=`val 诊断已排队（${result.id}）。完成后点击“重新读取诊断记录”选择结果。`
  }catch(reason){error.value=reason instanceof Error?reason.message:'创建诊断失败'}
  finally{busy.value=false}
}
onMounted(() => { dialog.value?.showModal(); void load() })
</script>
<template>
  <dialog ref="dialog" class="al-dialog al-create" aria-labelledby="al-create-title" @cancel.prevent="!busy && emit('close')">
    <form @submit.prevent="submit">
      <header><div><h2 id="al-create-title">新建主动学习任务</h2><p>系统推荐样本，人工确认标注，再准备下一轮训练。</p></div><button type="button" class="button" :disabled="busy" @click="emit('close')">关闭</button></header>
      <div class="al-dialog-content">
        <p v-if="error" class="al-error" role="alert">{{ error }} <button v-if="!options" type="button" class="button" @click="load">重试</button></p><p v-if="notice" class="al-note" role="status">{{notice}}</p>
        <p v-if="!options" role="status">正在读取模型、数据集和设备…</p>
        <fieldset :disabled="busy || !options">
          <h3>01　迭代与目标</h3>
          <label>所属迭代<select v-model="existing" :disabled="!!props.iteration || !!createdIteration"><option value="">创建新迭代</option><option v-for="item in iterations.filter(i => !i.completedAt)" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
          <template v-if="!selectedIteration && !createdIteration">
            <label>迭代名称<input v-model.trim="name" required maxlength="120"></label>
            <label>本轮优化目标<textarea v-model="goal" maxlength="2000" rows="2" /></label>
            <label>基线模型<select v-model="modelId" required><option value="" disabled>选择已注册模型</option><option v-for="item in options?.models" :key="item.id" :value="item.id">{{ item.displayName || item.name }} · {{ taskLabels[item.taskType] }}</option></select></label>
            <label>目标数据集<select v-model="datasetId" :required="datasets.length !== 1"><option value="">{{ datasets.length === 1 ? datasets[0]?.name : '先选择基线模型' }}</option><option v-for="item in datasets" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
          </template>
          <p v-else class="al-note">沿用迭代的基线、目标数据集与固定 val。{{ selectedIteration?.name ?? createdIteration?.name }}</p>
          <h3>02　推荐配置</h3>
          <fieldset class="al-strategies">
            <legend>推荐策略</legend>
            <div class="al-strategy-grid">
              <label v-for="item in strategies" :key="item.value" class="al-strategy-card" :class="{ selected: config.strategy === item.value }">
                <span class="al-strategy-title">
                  <input v-model="config.strategy" type="radio" name="recommendation-strategy" :value="item.value">
                  <strong>{{ strategyLabels[item.value] }}</strong>
                  <span v-if="item.value === 'mixed'" class="al-strategy-badge">推荐</span>
                </span>
                <span class="al-strategy-description">{{ item.description }}</span>
              </label>
            </div>
          </fieldset>
          <label v-if="config.strategy !== 'low_confidence'">基线 val 诊断<select v-model="config.evaluationId" required><option :value="undefined" disabled>选择已完成的固定 val 诊断</option><option v-for="item in evaluations" :key="item.id" :value="item.id">{{ item.id }}</option></select><small>若无可选记录，先为基线创建 val 诊断。test 不用于选样。</small></label>
          <div v-if="config.strategy !== 'low_confidence'" class="al-actions"><button type="button" class="button" :disabled="!model || busy" @click="diagnose">创建基线 val 诊断</button><button type="button" class="button" @click="load">重新读取诊断记录</button></div>
          <div class="al-field-grid">
            <label>问题参考上限<input v-model.number="config.referenceLimit" type="number" min="1" max="1000" required></label>
            <label>训练候选上限<input v-model.number="config.candidateLimit" type="number" min="1" max="1000" required></label>
            <label>推理保留阈值<input v-model.number="config.retainConfidence" type="number" min="0" max="1" step="0.01" required></label>
            <label>低置信度下限<input v-model.number="config.minConfidence" type="number" :min="config.retainConfidence" :max="config.maxConfidence - .001" step="0.001" required></label>
            <label>低置信度上限（不含）<input v-model.number="config.maxConfidence" type="number" :min="config.minConfidence + .001" max="1" step="0.001" required></label>
            <label>NMS 阈值<input v-model.number="config.nmsIou" type="number" min="0.01" max="1" step="0.01" required></label>
            <label>计算设备<select v-model="config.deviceId"><option v-for="item in options?.devices" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
            <label>输入尺寸<input v-model.number="config.imageSize" type="number" min="32" max="2048" step="32" required></label>
          </div>
          <label class="al-inline"><input v-model="config.includeNoPredictions" type="checkbox">纳入“无预测结果，待检查”图片</label>
          <p class="al-note">{{ strategyLabels[config.strategy] }}：参考图仅指导分析，训练候选需人工选择和复核。混合推荐不执行自动相似检索。</p>
        </fieldset>
      </div>
      <footer><button type="button" class="button" :disabled="busy" @click="emit('close')">取消</button><button class="button primary" :disabled="busy || !options">{{ busy ? '提交中…' : '创建推荐任务' }}</button></footer>
    </form>
  </dialog>
</template>

<style scoped>
.al-strategies { margin: 16px 0; }
.al-strategies legend { margin-bottom: 10px; font-weight: 600; }
.al-strategy-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.al-strategy-card { margin: 0; padding: 16px; border: 2px solid var(--line, #c8d2df); border-radius: 3px; background: var(--soft, #f5f7fa); cursor: pointer; }
.al-strategy-card.selected { border-color: var(--primary, #4f6885); background: #edf3fc; }
.al-strategy-card:focus-within { outline: 2px solid var(--primary, #4f6885); outline-offset: 3px; }
.al-strategy-title { display: flex; align-items: center; gap: 8px; min-height: 24px; }
.al-strategy-title input { flex: none; width: 18px; height: 18px; margin: 0; padding: 0; accent-color: var(--primary, #4f6885); }
.al-strategy-title strong { font-size: 15px; }
.al-strategy-badge { margin-left: auto; padding: 2px 6px; border-radius: 2px; background: var(--primary, #4f6885); color: #fff; font-size: 12px; white-space: nowrap; }
.al-strategy-description { font-size: 13px; line-height: 1.6; }
.al-strategy-card:has(input:disabled) { cursor: default; opacity: .6; }
@media (max-width: 700px) { .al-strategy-grid { grid-template-columns: 1fr; } }
</style>
