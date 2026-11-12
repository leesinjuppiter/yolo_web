<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import AnnotationCanvas from '../../annotation/AnnotationCanvas.vue'
import { AnnotationImageCache } from '../../annotation/image-cache'
import type { Candidate, ActiveTaskType } from '../../types/active-learning'
const props=defineProps<{candidate:Candidate;task:ActiveTaskType}>()
const layer=ref<'raw'|'prediction'|'truth'>('prediction'), raster=shallowRef<HTMLImageElement>()
const state=ref<'loading'|'ready'|'error'>('loading'), canvas=ref<InstanceType<typeof AnnotationCanvas>>()
const cache=new AnnotationImageCache()
const values=computed(()=>layer.value==='prediction'?props.candidate.predictions??[]:layer.value==='truth'?props.candidate.image?.annotations??[]:[])
async function load(){
  const src=props.candidate.image?.src
  raster.value=undefined;state.value='loading'
  if(!src){state.value='error';return}
  try{const image=await cache.load(src,'high');if(src===props.candidate.image?.src){raster.value=image;state.value='ready';cache.retain([src])}}
  catch{if(src===props.candidate.image?.src)state.value='error'}
}
watch(()=>props.candidate.image?.src,load,{immediate:true})
onBeforeUnmount(()=>cache.clear())
</script>
<template>
  <div class="al-toolbar"><select v-model="layer" aria-label="预览图层"><option value="raw">原图</option><option value="prediction">模型预测（只读）</option><option value="truth">{{candidate.purpose==='reference'?'冻结真实标注':'已保存标注'}}</option></select><button class="button" @click="canvas?.zoomBy(1.25)">＋</button><button class="button" @click="canvas?.zoomBy(.8)">−</button><button class="button" @click="canvas?.fit()">适应</button></div>
  <div class="al-canvas" style="height:300px;min-height:300px;flex:none"><AnnotationCanvas v-if="candidate.image" ref="canvas" :image="candidate.image" :raster="raster" :source-state="state" :annotations="values" :hidden-annotation-ids="new Set()" :classes="candidate.classes??[]" :task="task" tool="pan" selected-id="" active-class-id="" active-keypoint="" :active-visibility="2" :keypoint-names="[]" busy /></div>
  <button v-if="state==='error'" class="button" @click="load">重试原图</button>
</template>
