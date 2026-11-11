<script setup lang="ts">
import { onMounted,ref,watch } from 'vue'
import { evaluateModel } from '../../api/evaluation'
import { createExport } from '../../api/deployment'
import type { ModelVersion } from '../../types/models'
const props=defineProps<{model:ModelVersion;action:'evaluate'|'export'}>()
const emit=defineEmits<{close:[];created:[id:string]}>()
const dialog=ref<HTMLDialogElement>(),imgsz=ref(640),busy=ref(false),error=ref('')
let key=crypto.randomUUID()
watch(imgsz,()=>{key=crypto.randomUUID()})
onMounted(()=>{imgsz.value=props.model.config?.imageSize??640;dialog.value?.showModal()})
async function submit(){
 if(busy.value)return
 busy.value=true;error.value=''
 try{const job=props.action==='evaluate'?await evaluateModel(props.model.id,imgsz.value,key):await createExport(props.model.id,imgsz.value,key);emit('created',job.id)}
 catch(reason){error.value=reason instanceof Error?reason.message:'创建任务失败'}
 finally{busy.value=false}
}
</script>
<template>
 <dialog ref="dialog" class="model-dialog" @cancel.prevent="!busy&&emit('close')">
  <form @submit.prevent="submit">
   <div class="model-section-title"><h2>{{action==='evaluate'?'独立评估':'导出 ONNX 模型'}}</h2><button type="button" class="button" :disabled="busy" @click="emit('close')">关闭</button></div>
   <p><strong>{{model.displayName||model.name}}</strong> · {{model.version}} · {{model.taskType.toUpperCase()}}</p>
   <p class="model-muted">{{action==='evaluate'?'使用来源训练快照中的 test 分集，固定数据与类别；缺少测试集或检测到数据重叠时会拒绝执行。':'生成 ONNX FP32 产物，并记录实际加载、精度对照和性能验证结果。部署包需在导出完成后单独生成。'}}</p>
   <label class="model-field">输入尺寸<input v-model.number="imgsz" required type="number" min="320" max="2048" step="32"></label>
   <div class="model-note">执行设备：CPU · {{action==='export'?'ONNX / FP32 · ':' '}}任务在后台排队执行，可从任务中心查询日志。</div>
   <p v-if="error" class="model-error" role="alert">{{error}}</p>
   <div class="model-dialog-actions"><button type="button" class="button" :disabled="busy" @click="emit('close')">取消</button><button class="button primary" :disabled="busy">{{busy?'正在提交…':'创建任务'}}</button></div>
  </form>
 </dialog>
</template>
