<script setup lang="ts">
import { computed,onActivated,onDeactivated,onUnmounted,ref,watch } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { compareModels } from '../api/models'
import { formatValue } from '../types/models'
import type { Comparison } from '../types/models'
const route=useRoute(),router=useRouter(),result=ref<Comparison>(),error=ref(''),loading=ref(false),baseline=ref(''),diffOnly=ref(false)
const ids=computed(()=>String(route.query.ids??'').split(',').filter(Boolean))
const rows=computed(()=>result.value?.rows.filter(row=>!diffOnly.value||new Set(Object.values(row.values)).size>1)??[])
const deltaLabel=(value:number|null|undefined,unit:string)=>value==null?'—':formatValue(unit==='ratio'?value*100:value)+(unit==='ratio'?' pp':' '+unit)
let active=false,controller:AbortController|undefined
async function load(){
 if(!active)return
 controller?.abort();controller=new AbortController();const signal=controller.signal
 loading.value=true;error.value=''
 try{const data=await compareModels(ids.value,baseline.value||ids.value[0]||'',signal);if(!signal.aborted){result.value=data;baseline.value=data.baselineId}}
 catch(reason){if(!signal.aborted)error.value=reason instanceof Error?reason.message:'读取对比失败'}
 finally{if(!signal.aborted)loading.value=false}
}
watch(baseline,(value,old)=>{if(old&&value!==old)void load()})
watch(()=>route.query.ids,()=>{baseline.value='';void load()})
onActivated(()=>{active=true;void load()})
function stop(){active=false;controller?.abort()}
onDeactivated(stop);onUnmounted(stop)
function download(kind:'json'|'csv'){
 if(!result.value)return
 const quote=(value:unknown)=>'"'+String(value??'').replace(/"/g,'""').replace(/^[=+@-]/,"'")+'"'
 const body=kind==='json'?JSON.stringify(result.value,null,2):'\uFEFF'+[['指标','单位',...result.value.models.map(m=>m.name+' '+m.version)],...rows.value.map(row=>[row.label,row.unit,...result.value!.models.map(m=>row.values[m.id])])].map(row=>row.map(quote).join(',')).join('\r\n')
 const url=URL.createObjectURL(new Blob([body],{type:kind==='json'?'application/json':'text/csv;charset=utf-8'})),link=document.createElement('a')
 link.href=url;link.download='model-comparison.'+kind;link.click();URL.revokeObjectURL(url)
}
</script>
<template>
 <section class="model-workspace">
  <div class="model-page-heading"><div><h1>多模型对比</h1><p>依据固定数据与协议比较，原始指标保留来源</p></div><button class="button" @click="router.push({name:'models'})">返回模型仓库</button></div>
  <p v-if="error" class="model-error" role="alert">{{error}} <button class="button" @click="load">重试</button></p>
  <div v-if="loading&&!result" class="page-state">正在核对模型与评估条件…</div>
  <template v-if="result">
   <div class="model-panel"><div class="model-toolbar"><span v-for="model in result.models" :key="model.id" class="model-chip">{{model.displayName||model.name}} · {{model.version}}</span></div><div class="model-toolbar"><label>差量基准 <select v-model="baseline"><option v-for="model in result.models" :key="model.id" :value="model.id">{{model.displayName||model.name}} · {{model.version}}</option></select></label><label><input v-model="diffOnly" type="checkbox"> 仅看差异</label><button class="button" @click="download('json')">下载 JSON</button><button class="button" @click="download('csv')">下载 CSV</button></div></div>
   <div class="model-note" :class="{'model-error':!result.comparable}"><strong>{{result.comparable?'评估条件一致，可查看差量':'尚不满足严格比较条件'}}</strong><p v-for="reason in result.reasons" :key="reason">{{reason}}</p><p>精度差量按报告单位解释。不同设备和运行条件的速度不能据此排序。</p></div>
   <div class="model-panel model-table-scroll"><table class="model-table model-diff-table"><thead><tr><th>对比维度</th><th v-for="model in result.models" :key="model.id">{{model.displayName||model.name}}<small>{{model.version}}{{model.id===baseline?' · 基准':''}}</small></th></tr></thead><tbody><tr><th>任务类型</th><td v-for="model in result.models" :key="model.id">{{model.taskType.toUpperCase()}}</td></tr><tr><th>来源数据集</th><td v-for="model in result.models" :key="model.id">{{model.datasetName}}</td></tr><tr><th>独立评估</th><td v-for="model in result.models" :key="model.id">{{model.evaluation?'已有报告':'未评估'}}</td></tr><tr v-for="row in rows" :key="row.key"><th>{{row.label}}<small>{{row.unit==='ratio'?'比例 0–1':row.unit}}</small></th><td v-for="model in result.models" :key="model.id">{{formatValue(row.values[model.id])}}<small v-if="result.comparable&&model.id!==baseline&&row.deltas[model.id]!=null">Δ {{deltaLabel(row.deltas[model.id],row.unit)}}</small></td></tr></tbody></table></div>
  </template>
 </section>
</template>
