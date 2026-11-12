<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as api from '../api/active-learning'
import { changeRefresh, observeChanges } from '../api/changes'
import { getDataset } from '../api/datasets'
import { getTraining } from '../api/training'
import { listEvaluations } from '../api/evaluation'
import { startup } from '../startup'
import type { Candidate, Comparison, Iteration, Overview, Page, RecommendationTask, TrainingInput, ActiveLog } from '../types/active-learning'
import type { DatasetImage } from '../domain'
import type { TrainingConfig } from '../types/training'
import type { ModelJob } from '../types/models'
import { phaseLabels, strategyLabels } from '../types/active-learning'
import { taskLabels } from '../domain'
import { formatDate, jobLabels } from '../types/models'
import { createUuid } from '../utils/id'
import CreateActiveTaskDialog from '../components/active-learning/CreateActiveTaskDialog.vue'
import PrepareTrainingDialog from '../components/active-learning/PrepareTrainingDialog.vue'
import ActiveReview from '../components/active-learning/ActiveReview.vue'
import CandidatePreview from '../components/active-learning/CandidatePreview.vue'
import CreateTrainingDialog from '../components/training/CreateTrainingDialog.vue'
import '../components/active-learning/active-learning.css'

const router = useRouter(), route = useRoute()
let initial = startup.take<{overview:Overview;iterations:Page<Iteration>}>('active-learning')
const iterations = ref<Iteration[]>([]), tasks = ref<RecommendationTask[]>([]), overview = ref<Overview>(), total = ref(0)
const iteration = ref<Iteration>(), task = ref<RecommendationTask>(), candidates = ref<Candidate[]>([]), candidateTotal = ref(0), detail = ref<Candidate>()
const comparison = ref<Comparison>(), logs = ref<ActiveLog[]>([]), evaluations = ref<ModelJob[]>([])
const tab = ref<'iterations'|'tasks'>('iterations'), purpose = ref<'training'|'reference'>('training'), query = ref(''), status = ref(''), reason = ref(''), selectedFilter = ref(''), page = ref(1), candidatePage = ref(1)
const loading = ref(false), busy = ref(false), error = ref(''), notice = ref(''), connection = ref('connecting')
const creating = ref(false), preparing = ref(false), trainingDraft = ref<TrainingConfig>()
const pickDialog = ref<HTMLDialogElement>(), sourceImages = ref<DatasetImage[]>([]), chosenImages = ref<string[]>([]), referenceInput = ref('')
const resultVersionId = ref(''), baselineEvaluationId = ref(''), resultEvaluationId = ref('')
const mode = computed(() => route.name === 'active-learning-task' ? 'task' : route.name === 'active-learning-review' ? 'review' : route.name === 'active-learning-iteration' ? 'iteration' : 'list')
const count = computed(() => iteration.value?.counts)
let controller: AbortController | undefined, unsubscribe: (()=>void) | undefined, active = false
function navigate(name: string, id?: string) { void router.push({name, params:id ? name==='active-learning-task' ? {taskId:id} : {iterationId:id} : {}}) }
function params() { return new URLSearchParams({page:String(page.value),page_size:'10',query:query.value,status:status.value}) }
async function refresh() {
  if (!active) return
  controller?.abort(); controller = new AbortController(); const signal = controller.signal
  loading.value = true; error.value = ''
  try {
    if (mode.value === 'list') {
      const [summary, result] = await Promise.all([api.activeOverview(signal),tab.value==='iterations' ? api.listIterations(params(),signal) : api.listActiveTasks(params(),signal)])
      if (signal.aborted) return
      overview.value = summary; total.value = result.total
      if (tab.value==='iterations') iterations.value = result.items as Iteration[]
      else tasks.value = result.items as RecommendationTask[]
    } else if (mode.value === 'task') {
      const current = await api.getActiveTask(String(route.params.taskId),signal)
      const [round, list, history] = await Promise.all([api.getIteration(current.iterationId,signal),api.listCandidates(current.id,new URLSearchParams({purpose:purpose.value,page:String(candidatePage.value),page_size:'12',reason:reason.value,selected:selectedFilter.value}),signal),api.activeLogs(current.id)])
      if (signal.aborted) return
      task.value=current; iteration.value=round; candidates.value=list.items; candidateTotal.value=list.total; logs.value=history.items
    } else {
      const round = await api.getIteration(String(route.params.iterationId),signal)
      if (signal.aborted) return
      if(iteration.value?.id!==round.id) {
        resultVersionId.value=round.resultVersionId??''
        baselineEvaluationId.value=round.baselineEvaluationId??''
        resultEvaluationId.value=round.resultEvaluationId??''
      }
      iteration.value=round
      if (mode.value==='iteration') comparison.value=await api.activeComparison(round.id)
    }
  } catch (value) { if (!signal.aborted) error.value=value instanceof Error?value.message:'读取主动学习数据失败' }
  finally { if (!signal.aborted) loading.value=false }
}
async function action(run:()=>Promise<unknown>, message='') {
  if (busy.value) return
  busy.value=true; error.value=''
  try { await run();notice.value=message;await refresh() }
  catch (value) {error.value=value instanceof Error?value.message:'操作失败'}
  finally {busy.value=false}
}
async function inspect(item:Candidate) {
  try { detail.value=await api.candidateDetail(item.id);referenceInput.value=detail.value.referenceIds?.join(', ')??'' }
  catch(value){error.value=value instanceof Error?value.message:'读取证据失败'}
}
async function pickImages() {
  if(!iteration.value)return
  try { const data=await getDataset(iteration.value.datasetId);sourceImages.value=data.images.filter(item=>item.split!=='val'&&item.split!=='test');chosenImages.value=[];pickDialog.value?.showModal() }
  catch(value){error.value=value instanceof Error?value.message:'读取目标数据集失败'}
}
async function addImages() {
  if(!iteration.value)return
  await action(async()=>{
    const result=await api.addCandidates(iteration.value!.id,chosenImages.value)
    await api.selectCandidates(iteration.value!.id,result.candidateIds,true)
  },'已加入复核队列，请逐张检查并确认')
  if(!error.value)pickDialog.value?.close()
}
async function train(input:TrainingInput) {
  error.value=''
  try {
    const round=iteration.value ?? await api.getIteration(input.iterationId)
    const source=await getTraining(round.sourceTaskId)
    trainingDraft.value={...source.config,name:round.name+' · 下一轮',datasetId:input.datasetId,task:input.task,modelId:input.modelId,
      iterationId:input.iterationId,manifestId:input.manifestId,manifestDigest:input.manifestDigest}
    preparing.value=false
  } catch(value){error.value=value instanceof Error?value.message:'读取基线训练配置失败'}
}
async function loadResultOptions() {
  try { evaluations.value=(await listEvaluations()).items }
  catch(value){error.value=value instanceof Error?value.message:'读取评估记录失败'}
}
async function diagnoseResult() {
  if(!iteration.value || !resultVersionId.value)return
  await action(async()=>{
    const baseline=evaluations.value.find(item=>item.id===baselineEvaluationId.value)
    const size=Number(baseline?.config.imgsz??640)
    await api.createValDiagnostic(resultVersionId.value,iteration.value!.sourceTaskId,size,createUuid())
  },'结果模型 val 诊断已排队，完成后重新读取评估记录。')
}
function activate() {
  if(active)return
  active=true;const updates=changeRefresh(refresh)
  const stop=observeChanges(change=>{if(!change||['active_learning','iterations','evaluations','training','models'].includes(change.topic))updates.notify()},state=>connection.value=state)
  unsubscribe=()=>{stop();updates.stop()}
  if(initial && !initial.stale && mode.value==='list') {
    overview.value=initial.value.overview;iterations.value=initial.value.iterations.items;total.value=initial.value.iterations.total
  } else void refresh()
  initial=undefined
}
function deactivate(){active=false;controller?.abort();unsubscribe?.();unsubscribe=undefined}
watch(()=>route.fullPath,()=>{detail.value=undefined;void refresh()})
watch([tab,page,purpose,candidatePage,reason,selectedFilter],()=>void refresh())
onMounted(activate);onActivated(activate);onDeactivated(deactivate);onBeforeUnmount(deactivate)
</script>
<template>
  <section class="al-workspace">
    <header class="al-heading"><div><button v-if="mode!=='list'" class="button" @click="navigate('active-learning')">返回主动学习</button><h1>{{ mode==='task'?'推荐任务详情':mode==='iteration'?'迭代详情':mode==='review'?'人工复核':'主动学习' }}</h1><p>围绕模型问题选择样本，人工复核后进入下一轮训练。</p></div><div class="al-actions"><small>{{ connection==='connected'?'变化通知已连接':'正在恢复连接' }}</small><button class="button" :disabled="loading" @click="refresh">{{loading?'加载中…':'手动刷新'}}</button><button class="button primary" :disabled="busy" @click="creating=true">新建推荐任务</button></div></header>
    <p v-if="error" class="al-error" role="alert">{{error}} <button class="button" @click="refresh">重试</button></p><p v-if="notice" class="al-note" role="status">{{notice}}</p>
    <template v-if="mode==='list'">
      <div class="al-stats"><div><span>进行中的迭代</span><strong>{{overview?.activeIterations??'—'}}</strong></div><div><span>待复核训练样本</span><strong>{{overview?.pendingReview??'—'}}</strong></div><div><span>有效已复核样本</span><strong>{{overview?.reviewed??'—'}}</strong></div><div><span>待评估结果模型</span><strong>{{overview?.pendingEvaluation??'—'}}</strong></div></div>
      <div class="al-panel"><div class="al-toolbar"><button class="button" :class="{primary:tab==='iterations'}" @click="tab='iterations';page=1">迭代记录</button><button class="button" :class="{primary:tab==='tasks'}" @click="tab='tasks';page=1">推荐任务</button><form class="al-search" @submit.prevent="page=1;refresh()"><input v-model="query" placeholder="搜索名称或优化目标"><button class="button">搜索</button></form><select v-model="status" @change="page=1;refresh()"><option value="">全部状态</option><option v-for="state in tab==='tasks'?['queued','running','succeeded','failed','canceled']:['active','completed']" :key="state" :value="state">{{phaseLabels[state]??state}}</option></select></div>
        <div class="al-table-wrap"><table><thead><tr><th>名称 / 任务</th><th>类型 / 策略</th><th>当前阶段</th><th>{{tab==='iterations'?'已复核 / 已选择':'处理进度'}}</th><th>创建时间</th><th>操作</th></tr></thead><tbody v-if="tab==='iterations'"><tr v-for="item in iterations" :key="item.id"><td><strong>{{item.name}}</strong><small>{{item.goal}}</small></td><td>{{taskLabels[item.taskType]}}</td><td>{{phaseLabels[item.phase]??item.phase}}</td><td>{{item.counts.reviewed}} / {{item.counts.selected}}</td><td>{{formatDate(item.createdAt)}}</td><td><button class="button" @click="navigate('active-learning-iteration',item.id)">详情</button><button class="button" @click="navigate('active-learning-review',item.id)">进入复核</button></td></tr></tbody><tbody v-else><tr v-for="item in tasks" :key="item.id"><td><code>{{item.id}}</code></td><td>{{strategyLabels[item.strategy]}}</td><td>{{jobLabels[item.status]??item.status}}<small>{{item.phase}}</small></td><td>{{item.processed}} / {{item.total}}</td><td>{{formatDate(item.createdAt)}}</td><td><button class="button" @click="navigate('active-learning-task',item.id)">查看详情</button></td></tr></tbody></table></div>
        <p v-if="!loading && !total" class="al-empty">暂无记录，创建推荐任务开始第一轮迭代。</p><div class="al-pagination"><span>共 {{total}} 条</span><button class="button" :disabled="page<=1" @click="page--">上一页</button><span>{{page}} / {{Math.max(1,Math.ceil(total/10))}}</span><button class="button" :disabled="page*10>=total" @click="page++">下一页</button></div>
      </div>
    </template>
    <template v-else-if="mode==='task' && task && iteration">
      <div class="al-panel al-task-heading"><div><strong>{{iteration.name}}</strong><p>{{strategyLabels[task.strategy]}} · {{jobLabels[task.status]}} · {{task.processed}} / {{task.total}}</p><p v-if="task.error" class="al-error">{{task.error}}</p></div><div class="al-actions"><button v-if="['queued','running'].includes(task.status)" class="button" :disabled="busy || task.cancelRequested" @click="action(()=>api.cancelActiveTask(task!.id))">{{task.cancelRequested?'正在取消':'取消任务'}}</button><button class="button" @click="navigate('active-learning-review',iteration.id)">进入复核</button><button class="button" @click="pickImages">加入已有训练图 / 补采图</button></div></div>
      <div class="al-toolbar"><button class="button" :class="{primary:purpose==='reference'}" @click="purpose='reference';candidatePage=1">问题参考</button><button class="button" :class="{primary:purpose==='training'}" @click="purpose='training';candidatePage=1">训练候选</button><select v-model="reason"><option value="">全部原因</option><option value="low_confidence">低置信度</option><option value="no_predictions">无预测结果</option><option value="manual_revision">人工修订 / 补采</option></select><select v-model="selectedFilter"><option value="">全部选择状态</option><option value="true">已选择</option><option value="false">未选择</option></select></div>
      <p class="al-note">{{purpose==='reference'?'评估图只用于问题参考，请另采训练图片。':'选择图片后进入复核；无预测结果不代表已确认漏检。'}}</p>
      <div class="al-candidate-layout"><div><div class="al-candidate-grid"><article v-for="item in candidates" :key="item.id" class="al-candidate" :class="{selected:item.selected}"><button class="al-image-button" @click="inspect(item)"><img v-if="item.thumbnailUrl" :src="item.thumbnailUrl" :alt="item.name" loading="lazy"><span v-else>查看图片与证据</span></button><strong>{{item.name}}</strong><p>{{item.reasons.join('、')}}</p><small>{{item.confidence==null?'无预测分数':`置信度 ${item.confidence.toFixed(4)}`}}</small><div class="al-actions"><button class="button" @click="inspect(item)">查看证据</button><button v-if="purpose==='training'" class="button" :disabled="busy" @click="action(()=>api.selectCandidates(iteration!.id,[item.id],!item.selected))">{{item.selected?'取消选择':'加入复核队列'}}</button></div></article></div><p v-if="!loading && !candidates.length" class="al-empty">没有符合条件的图片。</p><div class="al-pagination"><span>共 {{candidateTotal}} 张</span><button class="button" :disabled="candidatePage<=1" @click="candidatePage--">上一页</button><span>{{candidatePage}}</span><button class="button" :disabled="candidatePage*12>=candidateTotal" @click="candidatePage++">下一页</button></div></div>
        <aside v-if="detail" class="al-panel al-evidence"><button class="button" @click="detail=undefined">关闭详情</button><h3>{{detail.name}}</h3><CandidatePreview :candidate="detail" :task="iteration.taskType"/><p>{{detail.reasons.join('、')}}</p><p>预测对象：{{detail.predictions?.length??0}} · {{detail.reviewState}}</p><p v-if="detail.unsupportedPrediction" class="al-error">预测包含当前格式不支持的轮廓，请人工绘制。</p><details v-if="detail.evidence"><summary>原始诊断证据</summary><pre>{{JSON.stringify(detail.evidence,null,2)}}</pre></details><template v-if="detail.purpose==='training'"><label>关联问题参考 ID（逗号分隔）<textarea v-model="referenceInput" rows="2" /></label><button class="button" :disabled="busy" @click="action(()=>api.linkReferences(detail!.id,referenceInput.split(/[,，\s]+/).filter(Boolean)),'关联已保存')">保存人工关联</button></template><p v-else class="al-note">参考 ID：{{detail.id}}。可在补采候选中人工关联此记录。</p></aside>
      </div><details class="al-panel"><summary>推荐任务日志</summary><pre>{{logs.map(item=>item.message).join('\n') || '暂无日志'}}</pre></details>
    </template>
    <ActiveReview v-else-if="mode==='review' && iteration" :iteration="iteration" @back="navigate('active-learning-iteration',iteration.id)" @updated="refresh" />
    <template v-else-if="mode==='iteration' && iteration">
      <div class="al-panel"><div class="al-task-heading"><div><h2>{{iteration.name}}</h2><p>{{iteration.goal}}</p><small>{{taskLabels[iteration.taskType]}} · {{phaseLabels[iteration.phase]??iteration.phase}}</small></div><div class="al-actions"><button class="button" @click="navigate('active-learning-review',iteration.id)">继续复核</button><button class="button primary" :disabled="!!iteration.completedAt" @click="preparing=true">准备下一轮训练</button><button class="button" @click="pickImages">加入已有训练图 / 补采图</button></div></div><ol class="al-stages"><li v-for="label in ['问题诊断','样本选择','人工复核','模型训练','固定 val 评估']" :key="label">{{label}}</li></ol><div class="al-stats"><div><span>已选择</span><strong>{{count?.selected??0}}</strong></div><div><span>有效已复核</span><strong>{{count?.reviewed??0}}</strong></div><div><span>新增 / 修订</span><strong>{{count?.new??0}} / {{count?.revised??0}}</strong></div><div><span>未改动 / 待复核</span><strong>{{count?.unchanged??0}} / {{count?.pending??0}}</strong></div></div></div>
      <div class="al-panel"><h3>关联推荐与训练尝试</h3><p v-for="item in iteration.tasks" :key="item.id"><button class="button" @click="navigate('active-learning-task',item.id)">{{strategyLabels[item.strategy]}} · {{jobLabels[item.status]}}</button></p><p v-for="item in iteration.trainingAttempts" :key="item.id"><button class="button" @click="router.push({name:'training-detail',params:{taskId:item.id}})">{{item.name || item.id}} · {{jobLabels[item.status]??item.status}}</button></p><p v-if="!iteration.trainingAttempts?.length">尚未创建训练尝试。</p></div>
      <div class="al-panel"><h3>效果比较</h3><p class="al-note">固定 val 用于本轮诊断和比较；最终 test 不回流选样。完成迭代不代表生产验收合格。</p><p v-if="!comparison?.comparable">{{comparison?.reasons.join('；') || '等待选择结果模型并完成同口径评估。'}}</p><table v-if="comparison?.rows.length"><thead><tr><th>指标</th><th>基线</th><th>本轮结果</th><th>变化（百分点）</th></tr></thead><tbody><tr v-for="row in comparison.rows" :key="row.key"><td>{{row.label}}</td><td>{{row.baseline==null?'—':(row.baseline*100).toFixed(2)+'%'}}</td><td>{{row.result==null?'待评估':(row.result*100).toFixed(2)+'%'}}</td><td>{{!comparison.comparable || row.delta==null?'—':(row.delta*100).toFixed(2)}}</td></tr></tbody></table><button class="button" @click="loadResultOptions">读取可选评估记录</button><div class="al-field-grid"><label>本轮结果模型<select v-model="resultVersionId"><option value="">选择成功训练已注册模型</option><option v-for="item in iteration.trainingAttempts?.filter(i=>i.modelVersionId)" :key="item.id" :value="item.modelVersionId">{{item.name || item.modelVersionId}}</option></select></label><label>基线 val 报告<select v-model="baselineEvaluationId"><option value="">选择报告</option><option v-for="item in evaluations.filter(e=>e.versionId===iteration?.baselineVersionId&&e.status==='succeeded')" :key="item.id" :value="item.id">{{item.id}}</option></select></label><label>结果 val 报告<select v-model="resultEvaluationId"><option value="">选择报告</option><option v-for="item in evaluations.filter(e=>e.versionId===resultVersionId&&e.status==='succeeded')" :key="item.id" :value="item.id">{{item.id}}</option></select></label></div><div class="al-actions"><button class="button" :disabled="busy || !resultVersionId" @click="diagnoseResult">为结果模型创建固定 val 诊断</button><button class="button" :disabled="busy || !resultVersionId || !baselineEvaluationId || !resultEvaluationId || !!iteration.completedAt" @click="action(()=>api.chooseActiveResult(iteration!.id,{versionId:resultVersionId,baselineEvaluationId,resultEvaluationId}),'结果模型与报告已关联')">保存结果选择</button><button class="button primary" :disabled="busy || !comparison?.comparable || !!iteration.completedAt" @click="action(()=>api.completeIteration(iteration!.id),'本轮迭代已完成')">{{iteration.completedAt?'迭代已完成':'完成本轮迭代'}}</button></div></div>
    </template>
    <p v-else-if="loading" role="status">正在加载页面…</p>
    <CreateActiveTaskDialog v-if="creating" :iterations="iterations" :iteration="mode==='list'?undefined:iteration" @close="creating=false" @created="creating=false;navigate('active-learning-task',$event)"/>
    <PrepareTrainingDialog v-if="preparing && iteration" :iteration="iteration" @close="preparing=false" @train="train"/>
    <CreateTrainingDialog v-if="trainingDraft" :initial-config="trainingDraft" :dataset-id="trainingDraft.datasetId" @close="trainingDraft=undefined" @created="trainingDraft=undefined;router.push({name:'training-detail',params:{taskId:$event}})"/>
    <dialog ref="pickDialog" class="al-dialog"><header><div><h2>加入训练候选</h2><p>仅列出目标数据集中的 train / 未分集图片；选择后仍须人工复核。</p></div><button class="button" @click="pickDialog?.close()">关闭</button></header><div class="al-dialog-content"><p v-if="error" class="al-error">{{error}}</p><label v-for="image in sourceImages" :key="image.id" class="al-inline"><input v-model="chosenImages" type="checkbox" :value="image.id">{{image.name}} · {{image.status}} · {{image.split??'未分集'}}</label><p v-if="!sourceImages.length">暂无可加入图片，请先在数据集中上传补采图片。</p></div><footer><button class="button primary" :disabled="busy || !chosenImages.length" @click="addImages">加入并选择 {{chosenImages.length}} 张复核</button></footer></dialog>
  </section>
</template>
