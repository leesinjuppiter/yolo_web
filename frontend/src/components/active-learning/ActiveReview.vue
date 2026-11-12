<script setup lang="ts">
import { computed, onActivated, onDeactivated, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import AnnotationCanvas from '../../annotation/AnnotationCanvas.vue'
import type { AnnotationTool } from '../../annotation/AnnotationCanvas.vue'
import type { Annotation, DatasetImage } from '../../domain'
import { updateAnnotations } from '../../api/datasets'
import { candidateDetail, confirmReview, reviewQueue, selectCandidates } from '../../api/active-learning'
import { changeRefresh, observeChanges } from '../../api/changes'
import { AnnotationImageCache, nearbyImages, thumbnailUrl } from '../../annotation/image-cache'
import { ForwardImageCache } from '../../annotation/forward-cache'
import type { CacheProgress } from '../../annotation/forward-cache'
import type { Candidate, Iteration } from '../../types/active-learning'
import { createUuid } from '../../utils/id'
const props = defineProps<{ iteration: Iteration }>()
const router = useRouter()
const emit = defineEmits<{ back: []; updated: [] }>()
const queue = ref<Candidate[]>([]), total = ref(0), page = ref(1), current = ref<Candidate>(), image = ref<DatasetImage>()
const annotations = ref<Annotation[]>([]), baseline = ref(''), selectedId = ref(''), classId = ref(''), tool = ref<AnnotationTool>('select')
const negative = ref(false), busy = ref(false), loading = ref(false), error = ref(''), notice = ref(''), stale = ref(false), draftPoints = ref(0)
const raster = shallowRef<HTMLImageElement>(), imageState = ref<'loading'|'ready'|'error'>('loading'), canvas = ref<InstanceType<typeof AnnotationCanvas>>()
const layer = ref<'manual'|'prediction'|'original'>('manual'), connection = ref('connecting')
const cache = new AnnotationImageCache(), forward = new ForwardImageCache(), progress = ref<CacheProgress>({loaded:0,total:0,failed:0,done:false})
const classes = computed(() => current.value?.classes ?? props.iteration.classes)
const displayed = computed(() => layer.value === 'prediction' ? current.value?.predictions ?? [] : layer.value === 'original' ? image.value?.annotations ?? [] : annotations.value)
const dirty = computed(() => !!image.value && (draftPoints.value > 0 || JSON.stringify([annotations.value, negative.value]) !== baseline.value))
const annotationStatus = computed(() => annotations.value.length ? 'annotated' : negative.value ? 'negative' : 'unlabeled')
const selected = computed(() => annotations.value.find(item => item.id === selectedId.value))
let unsubscribe: (() => void) | undefined, requestId = 0
let removeGuard: (() => void) | undefined
let active=false
function mayLeave() { return !dirty.value || window.confirm('有未保存的修改，是否放弃这些修改？') }
function back() { emit('back') }
async function loadQueue() {
  loading.value = true
  try {
    const data = await reviewQueue(props.iteration.id, new URLSearchParams({page:String(page.value),page_size:'20'}))
    queue.value = data.items; total.value = data.total
    if (current.value && dirty.value) {
      const update = data.items.find(item => item.id === current.value?.id)
      if (update?.image?.version !== undefined && update.image.version !== image.value?.version) stale.value = true
    } else if (current.value) {
      const update=data.items.find(item=>item.id===current.value?.id)
      if(update?.image?.version!==undefined && update.image.version!==image.value?.version) await open(update,true)
    } else if (data.items[0]) await open(data.items[0], true)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '读取复核队列失败' }
  finally { loading.value = false }
}
async function open(item: Candidate, force = false) {
  if (!force && !mayLeave()) return
  const id = ++requestId; error.value = ''; notice.value = ''
  try {
    const detail = await candidateDetail(item.id)
    if (id !== requestId) return
    current.value = detail; image.value = detail.image
    annotations.value = JSON.parse(JSON.stringify(detail.image?.annotations ?? []))
    negative.value = detail.image?.status === 'negative'; selectedId.value = ''; classId.value = detail.classes?.[0]?.id ?? props.iteration.classes[0]?.id ?? ''
    baseline.value = JSON.stringify([annotations.value, negative.value]); stale.value = false; layer.value = 'manual'; draftPoints.value = 0
    void loadImage()
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '读取图片失败' }
}
async function loadImage() {
  raster.value = undefined; imageState.value = 'loading'
  const src = image.value?.src, id = current.value?.id
  if (!src) { imageState.value = 'error'; return }
  try {
    const value = await cache.load(src, 'high')
    if (id !== current.value?.id) return
    raster.value = value; imageState.value = 'ready'; forward.markReady(src)
    const images = queue.value.flatMap(item => item.image ? [item.image] : [])
    const index = images.findIndex(item => item.id === image.value?.id)
    const near = nearbyImages(images, index).flatMap(item => item.src ? [item.src] : [])
    cache.retain(near); near.forEach(url => void cache.load(url).catch(() => {}))
    void forward.warm(images.slice(Math.max(index + 1, 0)).flatMap(item => item.src ? [item.src] : []), value => progress.value = value)
  } catch { if (id === current.value?.id) imageState.value = 'error' }
}
function update(annotation: Annotation) {
  if (layer.value !== 'manual') return
  annotations.value = annotations.value.map(item => item.id === annotation.id ? annotation : item)
}
function create(annotation: Annotation) { if (layer.value === 'manual') { annotations.value.push(annotation); negative.value = false; selectedId.value = annotation.id } }
function remove() { if(busy.value)return; annotations.value = annotations.value.filter(item => item.id !== selectedId.value); selectedId.value = '' }
function loadPredictions() {
  if (current.value?.unsupportedPrediction) { error.value = '部分预测包含当前标注格式不支持的轮廓，请人工绘制，不能直接载入。'; return }
  if (annotations.value.length && !window.confirm('载入预测将替换当前编辑草稿，是否继续？')) return
  annotations.value = (current.value?.predictions ?? []).map(item => ({...JSON.parse(JSON.stringify(item)),id:createUuid(),source:'manual'}))
  negative.value = false; layer.value = 'manual'; notice.value = '预测已载入草稿，请逐项检查后确认复核。'
}
function markNegative() {
  if (annotations.value.length && !window.confirm('确认此图无目标？此操作会清空当前草稿中的标注对象。')) return
  annotations.value = []; negative.value = true; layer.value = 'manual'
}
async function save(confirm = false) {
  if (!image.value || !current.value || busy.value || draftPoints.value || stale.value) return
  if (confirm && annotationStatus.value === 'unlabeled') { error.value = '请标注目标或明确确认无目标。'; return }
  busy.value = true; error.value = ''
  try {
    if (confirm) {
      await confirmReview(current.value.id, { version:image.value.version,annotations:annotations.value,
        status:annotationStatus.value,negativeConfirmed:negative.value })
      baseline.value = JSON.stringify([annotations.value, negative.value]); notice.value = '复核已确认'; emit('updated')
      const index = queue.value.findIndex(item => item.id === current.value?.id)
      const next = queue.value[index + 1]
      if (next) await open(next, true)
      else { current.value = undefined; image.value = undefined }
      await loadQueue()
    } else {
      const result = await updateAnnotations(props.iteration.datasetId, image.value, annotations.value, classes.value, annotationStatus.value)
      image.value = result.image; baseline.value = JSON.stringify([annotations.value, negative.value]); stale.value=false;notice.value = '草稿已保存，尚未确认复核'; emit('updated')
    }
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '保存失败，请核对版本后重试' }
  finally { busy.value = false }
}
async function removeFromQueue() {
  if (!current.value || !mayLeave()) return
  busy.value = true
  try { await selectCandidates(props.iteration.id,[current.value.id],false); current.value = undefined; image.value = undefined; await loadQueue(); emit('updated') }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '移出队列失败' }
  finally { busy.value = false }
}
function skip() { const next = queue.value[queue.value.findIndex(item => item.id === current.value?.id) + 1]; if (next) void open(next); else notice.value = '已到本页末尾；跳过的样本仍待复核。' }
function changePage(value: number) { if(mayLeave()) { baseline.value=JSON.stringify([annotations.value,negative.value]);page.value=value } }
function keyboard(event: KeyboardEvent) {
  if ((event.target as HTMLElement)?.closest('input,textarea,select,button')) return
  if (event.ctrlKey && event.key.toLowerCase() === 's') { event.preventDefault(); void save() }
  else if (event.key === 'Enter' && draftPoints.value) { event.preventDefault(); canvas.value?.finishPolygon() }
  else if (event.key === 'Delete' && layer.value === 'manual') remove()
}
function unload(event: BeforeUnloadEvent) { if (dirty.value) event.preventDefault() }
watch(page, () => { current.value = undefined; image.value=undefined; void loadQueue() })
function activate() {
  if(active)return
  active=true
  removeGuard=router.beforeEach((to,from)=>to.fullPath===from.fullPath || mayLeave())
  void loadQueue(); const updates = changeRefresh(loadQueue)
  const stop = observeChanges(change => { if (!change || ['active_learning','iterations','datasets'].includes(change.topic)) updates.notify() },state => connection.value = state)
  unsubscribe = () => {stop();updates.stop()}; window.addEventListener('keydown',keyboard); window.addEventListener('beforeunload',unload)
  if(image.value)void loadImage()
}
function deactivate() {
  active=false;unsubscribe?.();removeGuard?.();unsubscribe=undefined;removeGuard=undefined
  forward.stop();cache.clear();requestId++;window.removeEventListener('keydown',keyboard);window.removeEventListener('beforeunload',unload)
}
onMounted(activate);onActivated(activate);onDeactivated(deactivate);onBeforeUnmount(deactivate)
</script>
<template>
  <section class="al-review">
    <header class="al-heading"><div><button class="button" @click="back">返回迭代</button><h2>{{ iteration.name }} · 人工复核</h2><small>{{ connection === 'connected' ? '通知已连接' : '正在恢复连接' }} · {{ dirty ? '有未保存修改' : '草稿已保存' }} · {{ total }} 张选中</small></div><button class="button" :disabled="loading || busy" @click="loadQueue">刷新队列</button></header>
    <p v-if="error" class="al-error" role="alert">{{ error }}</p><p v-if="notice" class="al-note" role="status">{{ notice }}</p>
    <p v-if="stale" class="al-error">当前图片有外部更新，草稿已保留。请先复制需要保留的修改，再重新载入。<button class="button" @click="current && open(current)">重新载入</button></p>
    <div class="al-review-layout">
      <aside class="al-review-queue"><button v-for="item in queue" :key="item.id" class="al-queue-item" :class="{active:item.id===current?.id}" :disabled="busy" @click="open(item)"><img v-if="item.thumbnailUrl || item.image?.src" :src="item.thumbnailUrl || thumbnailUrl(item.image?.src)" alt=""><strong>{{ item.name }}</strong><small>{{ item.reviewState === 'reviewed' ? '已复核' : '待复核' }}</small></button><p v-if="!loading && !queue.length">暂无待处理图片。</p><div class="al-pagination"><button class="button" :disabled="page<=1 || busy" @click="changePage(page-1)">上一页</button><span>{{ page }} / {{ Math.max(1,Math.ceil(total/20)) }}</span><button class="button" :disabled="page*20>=total || busy" @click="changePage(page+1)">下一页</button></div></aside>
      <main class="al-review-main">
        <div class="al-toolbar"><select v-model="layer"><option value="manual">人工编辑</option><option value="prediction">模型预测（只读）</option><option value="original">已保存标注（只读）</option></select><button class="button" @click="tool='select'">选择</button><button class="button" @click="tool='draw';layer='manual'">{{ iteration.taskType==='segment' ? '绘制多边形' : iteration.taskType==='obb' ? '绘制旋转框' : '绘制框' }}</button><button class="button" @click="tool='pan'">平移</button><button class="button" @click="canvas?.zoomBy(.8)">−</button><button class="button" @click="canvas?.zoomBy(1.25)">＋</button><button class="button" @click="canvas?.fit()">适应</button><button v-if="draftPoints" class="button" @click="canvas?.finishPolygon()">完成多边形</button><button v-if="draftPoints" class="button" @click="canvas?.cancelDraft()">取消绘制</button></div>
        <div class="al-canvas"><AnnotationCanvas v-if="image" ref="canvas" :image="image" :raster="raster" :source-state="imageState" :annotations="displayed" :hidden-annotation-ids="new Set()" :classes="classes" :task="iteration.taskType" :tool="layer==='manual'?tool:'pan'" :selected-id="layer==='manual'?selectedId:''" :active-class-id="classId" active-keypoint="" :active-visibility="2" :keypoint-names="[]" :busy="busy || layer!=='manual'" @select="selectedId=$event" @create="create" @update="update" @draft="draftPoints=$event"/><p v-else>选择一张图片开始复核。</p></div>
        <div class="al-cache"><span>{{ imageState==='error' ? '原图加载失败' : progress.done ? '本页后续图片缓存结束' : '正在缓存本页后续图片' }}</span><progress :value="progress.loaded" :max="progress.total || 1"/><small>{{ progress.loaded }}/{{ progress.total }} · 失败 {{ progress.failed }}</small><button v-if="imageState==='error'" class="button" @click="loadImage">重试图片</button></div>
      </main>
      <aside class="al-review-tools"><h3>推荐依据</h3><p>{{ current?.reasons.join('、') || '人工选择修订' }}</p><p>预测置信度：{{ current?.confidence == null ? '无预测分数' : current.confidence.toFixed(4) }}</p><button class="button" :disabled="busy || !current?.predictions?.length || !!current?.unsupportedPrediction" @click="loadPredictions">载入预测到草稿</button><p v-if="current?.unsupportedPrediction" class="al-error">预测包含当前格式不支持的轮廓，请人工绘制。</p><h3>人工对象 {{ annotations.length }}</h3><button v-for="item in annotations" :key="item.id" class="al-object" :class="{active:selectedId===item.id}" @click="selectedId=item.id;layer='manual'">{{ classes.find(c=>c.id===item.class_id)?.name }} · {{ item.type }}</button><label>当前类别<select v-model="classId"><option v-for="item in classes" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label v-if="selected">对象类别<select :value="selected.class_id" @change="update({...selected,class_id:($event.target as HTMLSelectElement).value})"><option v-for="item in classes" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label v-if="selected?.type==='obb'">角度（°）<input type="number" :value="selected.obb.angle" @input="update({...selected,obb:{...selected.obb,angle:Number(($event.target as HTMLInputElement).value)}})"></label><button class="button" :disabled="!selectedId || busy" @click="remove">删除选中对象</button><button class="button" :disabled="busy || !image" @click="markNegative">确认无目标</button><p v-if="negative">已明确选择有效负样本。</p><button class="button" :disabled="busy || !current" @click="removeFromQueue">移出本轮队列</button></aside>
    </div>
    <footer class="al-review-footer"><span>{{ image?.name ?? '等待选择图片' }}</span><button class="button" :disabled="busy || !image || !dirty || stale || !!draftPoints" @click="save()">保存草稿</button><button class="button" :disabled="busy || !current" @click="skip">暂时跳过</button><button class="button primary" :disabled="busy || !image || stale || !!draftPoints" @click="save(true)">{{ busy ? '保存中…' : '确认复核并下一张' }}</button></footer>
  </section>
</template>
