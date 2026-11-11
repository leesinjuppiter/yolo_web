<script setup lang="ts">
import { computed,onActivated,onDeactivated,onUnmounted,ref,watch } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { refreshOnChanges } from '../api/changes'
import { startup } from '../startup'
import type { DeploymentPage } from '../startup'
import { cancelModelJob,createPackage,getModelJob,listModelJobs,modelJobLogs } from '../api/deployment'
import { cancelEvaluation,evaluationLogs,getEvaluation,listEvaluations } from '../api/evaluation'
import type { JobResource } from '../api/deployment'
import type { ModelJob,JobLog } from '../types/models'
import { formatDate,jobLabels } from '../types/models'
import ModelReport from '../components/models/ModelReport.vue'
import { createUuid } from '../utils/id'
const route=useRoute(),router=useRouter()
let initial=startup.take<DeploymentPage>('deployments')
type Tab='exports'|'packages'|'reports'
const tab=computed<Tab>(()=>route.query.tab==='packages'?'packages':route.query.tab==='reports'?'reports':'exports')
const items=ref<ModelJob[]>([]),exports=ref<ModelJob[]>([]),packages=ref<ModelJob[]>([]),evaluations=ref<ModelJob[]>([])
const selected=ref<ModelJob>(),logs=ref<JobLog[]>([]),query=ref(''),status=ref('all'),loading=ref(false),error=ref(''),busy=ref(false),notice=ref(''),page=ref(1),total=ref(0)
const pageCount=computed(()=>Math.max(1,Math.ceil(total.value/20)))
let active=false,controller:AbortController|undefined,unsubscribe:(()=>void)|undefined
const packageKeys=new Map<string,string>()
function versionId(item:ModelJob){return item.versionId||String(item.manifest?.modelVersionId??exports.value.find(job=>job.id===item.exportId)?.versionId??'—')}
const visible=computed(()=>items.value.filter(item=>(status.value==='all'||item.status===status.value)&&(!query.value.trim()||[item.id,versionId(item),item.exportId].join(' ').toLowerCase().includes(query.value.trim().toLowerCase()))))
const reportExports=computed(()=>exports.value.filter(item=>item.report))
const finishedPackages=computed(()=>packages.value.filter(item=>item.status==='succeeded').length)
const running=computed(()=>[...exports.value,...packages.value,...evaluations.value].filter(item=>['queued','running'].includes(item.status)).length)
const resource=computed<JobResource>(()=>tab.value==='packages'?'deployment-packages':'exports')
function stop(){controller?.abort();loading.value=false}
async function refresh(quiet=false,cached?:DeploymentPage){
 if(!active)return
 stop();controller=new AbortController();const signal=controller.signal;loading.value=!quiet;error.value=''
 const currentTab=tab.value,currentResource=resource.value,id=typeof route.query.job==='string'?route.query.job:''
 try{
  const [a,b,c]=cached??await Promise.all([listModelJobs('exports',signal,currentTab==='exports'?page.value:1),listModelJobs('deployment-packages',signal,currentTab==='packages'?page.value:1),listEvaluations(signal)])
  if(signal.aborted)return
  exports.value=a.items;packages.value=b.items;evaluations.value=c.items
  items.value=currentTab==='exports'?a.items:currentTab==='packages'?b.items:c.items
  total.value=currentTab==='exports'?a.total??a.items.length:currentTab==='packages'?b.total??b.items.length:c.items.length
  if(id){
   const job=currentTab==='reports'?await getEvaluation(id,signal):await getModelJob(currentResource,id,signal)
   const result=currentTab==='reports'?await evaluationLogs(id,signal):currentTab==='packages'?{items:job.logs??[]}:await modelJobLogs(currentResource,id,signal)
   if(!signal.aborted){selected.value=job;logs.value=result.items}
  }else {selected.value=undefined;logs.value=[]}
 }catch(reason){if(!signal.aborted)error.value=reason instanceof Error?reason.message:'读取任务失败'}
 finally{if(!signal.aborted&&active){loading.value=false}}
}
function switchTab(value:Tab){page.value=1;void router.replace({name:'deployments',query:{tab:value}})}
function open(id:string){void router.replace({name:'deployments',query:{tab:tab.value,job:id}})}
async function cancel(){
 if(!selected.value||busy.value)return
 busy.value=true
 try{if(tab.value==='reports')await cancelEvaluation(selected.value.id);else await cancelModelJob(resource.value,selected.value.id);void refresh()}
 catch(reason){error.value=reason instanceof Error?reason.message:'取消失败'}
 finally{busy.value=false}
}
async function build(id:string){
 if(busy.value)return
 busy.value=true;error.value=''
 try{if(!packageKeys.has(id))packageKeys.set(id,createUuid());const job=await createPackage(id,packageKeys.get(id));packageKeys.delete(id);notice.value='部署包构建任务已创建';void router.replace({name:'deployments',query:{tab:'packages',job:job.id}})}
 catch(reason){error.value=reason instanceof Error?reason.message:'创建部署包失败'}
 finally{busy.value=false}
}
function saveReport(job:ModelJob){const url=URL.createObjectURL(new Blob([JSON.stringify(job.report,null,2)],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download='report-'+job.id+'.json';link.click();URL.revokeObjectURL(url)}
watch(()=>route.fullPath,()=>{if(route.query.job!==selected.value?.id){selected.value=undefined;logs.value=[]}void refresh()})
watch(page,()=>void refresh())
onActivated(()=>{active=true;unsubscribe=refreshOnChanges(['exports','packages','evaluations'],()=>refresh(true));void refresh(false,initial&&!initial.stale?initial.value:undefined);initial=undefined})
onDeactivated(()=>{active=false;unsubscribe?.();stop()});onUnmounted(()=>{unsubscribe?.();stop()})
</script>
<template>
 <section class="model-workspace">
  <div class="model-page-heading"><div><h1>部署中心</h1><p>导出模型、核对验证报告并生成可下载的部署包</p></div><button class="button" :disabled="loading" @click="refresh()">刷新</button></div>
  <div class="model-stat-grid"><div><span>已载入导出任务</span><strong>{{exports.length}}</strong><small>Detect / OBB · ONNX FP32</small></div><div><span>已载入的成功部署包</span><strong>{{finishedPackages}}</strong><small>完整性校验与环境说明</small></div><div><span>已载入的等待或执行任务</span><strong>{{running}}</strong><small>评估、导出与包构建任务</small></div></div>
  <p class="model-note">本版本交付到部署包生成与下载。报告记录实际验证环境；目标机器上的运行兼容性需在接入后验证。</p>
  <p v-if="notice" role="status" class="model-note">{{notice}}</p>
  <div class="model-panel">
   <div class="model-tabs"><button :class="{active:tab==='exports'}" @click="switchTab('exports')">导出任务</button><button :class="{active:tab==='packages'}" @click="switchTab('packages')">部署包</button><button :class="{active:tab==='reports'}" @click="switchTab('reports')">验证报告</button></div>
   <p v-if="error" role="alert" class="model-error">{{error}} <button class="button" @click="refresh()">重试</button></p>
   <template v-if="selected">
    <div class="model-toolbar"><button class="button" @click="switchTab(tab)">返回{{tab==='exports'?'导出任务':tab==='packages'?'部署包':'验证报告'}}</button><span class="model-chip">{{jobLabels[selected.status]||selected.status}}</span><span>{{selected.phase}}</span><button v-if="tab!=='packages'&&['queued','running'].includes(selected.status)" class="button danger" :disabled="busy" @click="cancel">取消任务</button><a v-if="selected.downloadUrl&&selected.status==='succeeded'" class="button" :href="selected.downloadUrl">下载{{tab==='packages'?'部署包':'ONNX 产物'}}</a><button v-if="tab==='exports'&&selected.status==='succeeded'" class="button primary" :disabled="busy" @click="build(selected.id)">生成部署包</button></div>
    <dl class="model-facts model-detail"><div><dt>任务 ID</dt><dd>{{selected.id}}</dd></div><div><dt>模型版本 ID</dt><dd>{{versionId(selected)}}</dd></div><div><dt>创建时间</dt><dd>{{formatDate(selected.createdAt)}}</dd></div><div><dt>完成时间</dt><dd>{{formatDate(selected.finishedAt)}}</dd></div></dl>
    <p v-if="selected.error" class="model-error">{{selected.error}}</p>
    <div class="model-detail"><div v-if="selected.manifest"><h3>部署包清单</h3><p class="model-note">已生成可下载制品。运行环境与模型处理方式如下；生产目标兼容性需另行验证。</p><button class="button" @click="router.replace({name:'deployments',query:{tab:'exports',job:selected.exportId}})">查看来源导出与验证报告</button><pre class="model-json">{{JSON.stringify(selected.manifest,null,2)}}</pre></div><h3>执行配置</h3><pre class="model-json">{{JSON.stringify(selected.config,null,2)}}</pre><div class="model-section-title"><h3>验证报告</h3><button v-if="selected.report" class="button" @click="saveReport(selected)">下载报告 JSON</button></div><p v-if="!selected.report" class="model-muted">任务尚未产生报告。执行成功与业务精度达标需分别判断。</p><ModelReport v-else :report="selected.report"/><h3>执行日志</h3><pre class="model-log">{{logs.length?logs.map(line=>'['+line.level+'] '+line.message).join('\n'):'尚无日志'}}</pre></div>
   </template>
   <template v-else>
    <div class="model-toolbar"><input v-model="query" type="search" placeholder="搜索本页任务或模型版本 ID" aria-label="搜索任务"><select v-model="status" aria-label="任务状态"><option value="all">全部状态</option><option v-for="(label,value) in jobLabels" :key="value" :value="value">{{label}}</option></select><span v-if="loading" class="model-muted">正在刷新…</span></div>
    <div class="model-table-scroll"><table class="model-table"><thead><tr><th>{{tab==='packages'?'部署包 / 构建任务':'任务 ID'}}</th><th>模型版本</th><th>状态 / 阶段</th><th>创建时间</th><th>操作</th></tr></thead><tbody><tr v-for="item in visible" :key="item.id"><td class="model-mono">{{item.id}}</td><td class="model-mono">{{versionId(item)}}</td><td><span class="model-chip" :class="{good:item.status==='succeeded'}">{{jobLabels[item.status]||item.status}}</span><small>{{item.phase}}</small></td><td>{{formatDate(item.createdAt)}}</td><td><div class="model-toolbar compact"><button class="button" @click="open(item.id)">详情与日志</button><button v-if="tab==='exports'&&item.status==='succeeded'" class="button" :disabled="busy" @click="build(item.id)">生成部署包</button><a v-if="item.downloadUrl&&item.status==='succeeded'" class="button" :href="item.downloadUrl">下载</a></div></td></tr></tbody></table></div>
    <div v-if="tab!=='reports'" class="model-pagination"><span>共 {{total}} 条任务 · 筛选作用于本页</span><button class="button" :disabled="page<=1" @click="page--">上一页</button><span>{{page}} / {{pageCount}}</span><button class="button" :disabled="page>=pageCount" @click="page++">下一页</button></div><p v-if="!visible.length&&!loading" class="page-state">暂无匹配{{tab==='exports'?'导出任务':tab==='packages'?'部署包':'评估报告'}}。可从模型仓库详情创建评估或导出。</p>
    <div v-if="tab==='reports'&&reportExports.length" class="model-detail"><h3>导出产物验证报告</h3><div v-for="job in reportExports" :key="job.id" class="model-history-row"><span class="model-mono">{{job.id}}</span><button class="button" @click="router.replace({name:'deployments',query:{tab:'exports',job:job.id}})">查看精度与性能报告</button></div></div>
   </template>
  </div>
 </section>
</template>
