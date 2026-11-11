<script setup lang="ts">
import { computed,nextTick,onActivated,onDeactivated,onUnmounted,ref,watch } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { archiveModel,deleteModel,getModel,listModels,updateModel } from '../api/models'
import ModelActionDialog from '../components/models/ModelActionDialog.vue'
import { taskLabels } from '../domain'
import { formatDate,formatValue } from '../types/models'
import type { ModelVersion,RegistryList } from '../types/models'
const emit=defineEmits<{finetune:[model:ModelVersion]}>()
const router=useRouter(),route=useRoute()
const data=ref<RegistryList>(),error=ref(''),loading=ref(false),query=ref(''),task=ref('all'),lifecycle=ref('all'),page=ref(1)
const selected=ref<string[]>([]),detail=ref<ModelVersion>(),detailError=ref(''),detailLoading=ref(false)
const action=ref<'evaluate'|'export'>(),name=ref(''),description=ref(''),busy=ref(false),notice=ref('')
const deleteDialog=ref<HTMLDialogElement>(),deleteTarget=ref<ModelVersion>(),deleteError=ref('')
let active=false,timer:ReturnType<typeof setTimeout>|undefined,controller:AbortController|undefined,detailController:AbortController|undefined,listScroll=0
const pages=computed(()=>Math.max(1,Math.ceil((data.value?.total??0)/10)))
const types=['detect','segment','obb','classify'] as const
const canExecute=computed(()=>detail.value&&['detect','obb'].includes(detail.value.taskType)&&detail.value.lifecycle!=='archived')
const coreMetrics=computed(()=>{
 const model=detail.value
 if(!model)return []
 const keys=model.taskType==='classify'?[['top1','Top-1 准确率'],['top5','Top-5 准确率']]
  :model.taskType==='segment'?[['maskMap50','Mask mAP50'],['maskMap50_95','Mask mAP50–95'],['map50','Box mAP50'],['map50_95','Box mAP50–95']]
  :[['map50','mAP50'],['map50_95','mAP50–95'],['precision','Precision'],['recall','Recall']]
 return keys.map(([key,label])=>({key:key!,label,value:model.trainingMetrics[key!]}))
})
function stop(){clearTimeout(timer);controller?.abort();detailController?.abort();loading.value=false}
async function refresh(){
 if(!active)return
 clearTimeout(timer);controller?.abort();controller=new AbortController();const signal=controller.signal
 loading.value=true;error.value=''
 const params=new URLSearchParams({query:query.value,page:String(page.value),page_size:'10'})
 if(task.value!=='all')params.set('task',task.value)
 if(lifecycle.value!=='all')params.set('lifecycle',lifecycle.value)
 try{const result=await listModels(params,signal);if(!signal.aborted){data.value=result;if(page.value>pages.value)page.value=pages.value}}
 catch(reason){if(!signal.aborted)error.value=reason instanceof Error?reason.message:'读取失败'}
 finally{if(!signal.aborted&&active){loading.value=false;timer=setTimeout(refresh,10000)}}
}
async function loadDetail(){
 if(!active)return
 const id=typeof route.query.model==='string'?route.query.model:''
 detailController?.abort();detailError.value=''
 if(!id){detail.value=undefined;return}
 detailLoading.value=true;detailController=new AbortController();const signal=detailController.signal
 try{const value=await getModel(id,signal);if(!signal.aborted){detail.value=value;name.value=value.displayName||value.name;description.value=value.description||''}}
 catch(reason){if(!signal.aborted)detailError.value=reason instanceof Error?reason.message:'读取详情失败'}
 finally{if(!signal.aborted)detailLoading.value=false}
}
function open(id:string){listScroll=window.scrollY;void router.replace({name:'models',query:{model:id}});window.scrollTo(0,0)}
function back(){action.value=undefined;void router.replace({name:'models'})}
function requestDelete(){
 if(!detail.value||busy.value)return
 deleteTarget.value=detail.value;deleteError.value='';deleteDialog.value?.showModal()
}
function closeDelete(){if(!busy.value){deleteDialog.value?.close();deleteTarget.value=undefined}}
async function confirmDelete(){
 const target=deleteTarget.value
 if(!target||busy.value)return
 busy.value=true;deleteError.value=''
 try{
  await deleteModel(target.id)
  selected.value=selected.value.filter(id=>id!==target.id)
  deleteDialog.value?.close();deleteTarget.value=undefined
  notice.value='模型记录已删除，来源训练任务和权重文件已保留'
  if(route.query.model===target.id)back()
  void refresh()
 }catch(reason){deleteError.value=reason instanceof Error?reason.message:'删除失败，请重试'}
 finally{busy.value=false}
}
function toggle(id:string,checked:boolean){
 if(checked){if(selected.value.length>=4){notice.value='最多选择 4 个模型';return}selected.value=[...selected.value,id]}
 else selected.value=selected.value.filter(value=>value!==id)
}
async function mutate(kind:'save'|'archive'){
 if(!detail.value||busy.value)return
 busy.value=true;detailError.value=''
 try{detail.value=kind==='save'?await updateModel(detail.value.id,{displayName:name.value,description:description.value}):await archiveModel(detail.value.id,detail.value.lifecycle==='archived');notice.value=kind==='save'?'模型信息已保存':'模型状态已更新';void refresh()}
 catch(reason){detailError.value=reason instanceof Error?reason.message:'操作失败'}
 finally{busy.value=false}
}
function created(id:string){const type=action.value;action.value=undefined;void router.push({name:'deployments',query:{tab:type==='evaluate'?'reports':'exports',job:id}})}
function metric(model:ModelVersion){const values=model.trainingMetrics;return model.taskType==='classify'?'Top-1 '+formatValue(values.top1):model.taskType==='segment'?'Mask mAP50–95 '+formatValue(values.maskMap50_95):'mAP50–95 '+formatValue(values.map50_95)}
watch([query,task,lifecycle],()=>{page.value=1})
watch([query,task,lifecycle,page],()=>{if(active){clearTimeout(timer);controller?.abort();timer=setTimeout(refresh,200)}})
watch(()=>route.query.model,async(id,previous)=>{closeDelete();void loadDetail();if(!id&&previous){await nextTick();window.scrollTo(0,listScroll)}})
onActivated(()=>{active=true;void refresh();void loadDetail()})
onDeactivated(()=>{active=false;action.value=undefined;closeDelete();stop()})
onUnmounted(stop)
</script>
<template>
 <section class="model-workspace">
  <div class="model-page-heading"><div><h1>模型仓库</h1><p>为训练结果保留身份、来源与验证依据</p></div><button class="button" :disabled="loading" @click="refresh">刷新</button></div>
  <p v-if="notice" class="model-note" role="status">{{notice}} <button class="model-text-button" @click="notice=''">收起</button></p>
  <div class="model-stat-grid">
   <div><span>已注册模型版本</span><strong>{{data?.summary.total??'—'}}</strong><small>来自训练结果登记</small></div>
   <div><span>已完成独立评估</span><strong>{{data?.summary.evaluated??'—'}}</strong><small>查看报告了解评估条件</small></div>
   <div><span>已归档版本</span><strong>{{data?.summary.archived??'—'}}</strong><small>保留来源与历史记录</small></div>
  </div>
  <template v-if="!route.query.model">
   <div class="model-panel">
    <div class="model-toolbar"><input v-model="query" type="search" placeholder="搜索模型名称或版本" aria-label="搜索模型"><select v-model="lifecycle" aria-label="模型状态"><option value="all">全部状态</option><option value="candidate">候选模型</option><option value="archived">已归档</option></select><button class="button" :disabled="selected.length<2" @click="router.push({name:'model-compare',query:{ids:selected.join(',')}})">模型对比（{{selected.length}}/4）</button><button v-if="selected.length" class="model-text-button" @click="selected=[]">清空选择</button></div>
    <div class="model-tabs" aria-label="任务类型"><button :class="{active:task==='all'}" @click="task='all'">全部</button><button v-for="value in types" :key="value" :class="{active:task===value}" @click="task=value">{{taskLabels[value]}}</button></div>
    <p v-if="error" class="model-error" role="alert">{{error}} <button class="button" @click="refresh">重试</button></p>
    <div v-if="!data&&loading" class="page-state" role="status">正在读取模型版本…</div>
    <div v-else-if="data&&!data.items.length" class="page-state">没有匹配的模型版本。训练成功后，可在训练详情中注册模型。</div>
    <div v-else class="model-table-scroll"><table class="model-table"><thead><tr><th aria-label="选择"></th><th>模型名称 / 版本</th><th>任务类型</th><th>来源数据集</th><th>训练验证指标</th><th>验证与状态</th><th>操作</th></tr></thead><tbody><tr v-for="model in data?.items" :key="model.id"><td><input type="checkbox" :aria-label="'选择 '+model.name" :checked="selected.includes(model.id)" @change="toggle(model.id,($event.target as HTMLInputElement).checked)"></td><td><button class="model-link" @click="open(model.id)">{{model.displayName||model.name}}</button><small>{{model.version}} · {{formatDate(model.createdAt)}}</small></td><td><span class="model-chip">{{model.taskType.toUpperCase()}}</span><small>{{taskLabels[model.taskType]}}</small></td><td>{{model.datasetName}}<small class="model-mono">{{model.snapshotDigest?.slice(0,12)}}</small></td><td>{{metric(model)}}<small>来源：训练验证，非独立测试</small></td><td><span class="model-chip" :class="{good:!!model.evaluation}">{{model.evaluation?'已评估':'未独立评估'}}</span><small>{{model.lifecycle==='archived'?'已归档':'候选模型'}}</small></td><td><button class="button" @click="open(model.id)">详情与操作</button></td></tr></tbody></table></div>
    <div class="model-pagination"><span>共 {{data?.total??0}} 个版本<span v-if="loading"> · 正在刷新</span></span><button class="button" :disabled="page<=1" @click="page--">上一页</button><span>{{page}} / {{pages}}</span><button class="button" :disabled="page>=pages" @click="page++">下一页</button></div>
   </div>
  </template>
  <template v-else>
   <div class="model-toolbar"><button class="button" @click="back">返回模型仓库</button><span v-if="detailLoading">正在读取详情…</span></div>
   <p v-if="detailError" class="model-error" role="alert">{{detailError}}</p>
   <div v-if="detail" class="model-panel model-detail">
    <div class="model-section-title"><div><h2>{{detail.displayName||detail.name}} <span class="model-chip">{{detail.version}}</span></h2><p>{{taskLabels[detail.taskType]}} · {{detail.lifecycle==='archived'?'已归档':'候选模型'}}</p></div><button class="button" :disabled="busy" @click="mutate('archive')">{{detail.lifecycle==='archived'?'恢复为候选':'归档模型'}}</button></div>
    <div class="model-toolbar"><button class="button" :disabled="!canExecute" @click="action='evaluate'">创建独立评估</button><button class="button primary" :disabled="!canExecute" @click="action='export'">导出 ONNX FP32</button><button class="button" :disabled="detail.lifecycle==='archived'" @click="emit('finetune',detail)">使用此模型微调</button><button class="button" @click="router.push({name:'training-detail',params:{taskId:detail.taskId}})">查看来源训练</button><button class="button danger" :disabled="busy" @click="requestDelete">删除模型记录</button></div>
    <p v-if="!['detect','obb'].includes(detail.taskType)" class="model-note">首轮独立评估与导出仅开放目标检测和旋转框。此版本保留训练来源及指标。</p>
    <dl class="model-facts"><div><dt>来源数据集</dt><dd>{{detail.datasetName}}</dd></div><div><dt>训练任务</dt><dd>{{detail.taskId}}</dd></div><div><dt>快照摘要</dt><dd>{{detail.snapshotDigest}}</dd></div><div><dt>权重 SHA-256</dt><dd>{{detail.sha256}}</dd></div><div><dt>注册时间</dt><dd>{{formatDate(detail.createdAt)}}</dd></div><div><dt>验证依据</dt><dd>{{detail.evaluation?'已完成独立评估，结论见报告':'尚无独立评估报告'}}</dd></div></dl>
    <div class="model-edit-grid"><label class="model-field">显示名称<input v-model="name" maxlength="120"></label><label class="model-field">说明<input v-model="description" maxlength="2000"></label><button class="button" :disabled="busy||!name.trim()" @click="mutate('save')">保存信息</button></div>
    <h3>训练验证指标</h3><div class="model-metric-grid"><div v-for="metric in coreMetrics" :key="metric.key"><span>{{metric.label}}</span><strong>{{formatValue(metric.value)}}</strong></div></div><details><summary>完整原始训练指标</summary><pre class="model-json">{{JSON.stringify(detail.trainingMetrics,null,2)}}</pre></details>
    <h3>独立评估记录</h3><p v-if="!detail.evaluations?.length" class="model-muted">尚无记录。推理看图和训练验证不能替代独立测试。</p><div v-for="run in detail.evaluations" :key="run.id" class="model-history-row"><span>{{formatDate(run.createdAt)}} · {{run.status}}</span><button class="button" @click="router.push({name:'deployments',query:{tab:'reports',job:run.id}})">查看报告与日志</button></div>
   </div>
  </template>
  <ModelActionDialog v-if="detail&&action" :model="detail" :action="action" @close="action=undefined" @created="created"/>
  <dialog ref="deleteDialog" class="confirm-dialog" aria-labelledby="delete-model-title" @cancel.prevent="closeDelete">
   <h2 id="delete-model-title">确认删除模型记录？</h2>
   <p>将删除「{{deleteTarget?.displayName||deleteTarget?.name}}」{{deleteTarget?.version}} 的仓库记录，此操作无法撤销。</p>
   <p>来源训练任务和权重文件会保留。有评估、导出、部署包或后续训练引用时无法删除，可改用归档。</p>
   <p v-if="deleteError" class="model-error" role="alert">{{deleteError}}</p>
   <div class="actions"><button type="button" class="button" :disabled="busy" autofocus @click="closeDelete">取消</button><button type="button" class="button danger" :disabled="busy" @click="confirmDelete">{{busy?'正在删除…':'确认删除'}}</button></div>
  </dialog>
 </section>
</template>
