<script setup lang="ts">
import { computed } from 'vue'
import type { TrainingConfig, TrainingTask } from '../../types/training'

const props = defineProps<{ task: TrainingTask }>()
const emit = defineEmits<{ retrain: [config: TrainingConfig] }>()
type Row = [label: string, config: keyof TrainingConfig | null, actual: string]
const groups: { title: string; rows: Row[] }[] = [
  { title: '优化器与学习率', rows: [
    ['优化器', 'optimizer', 'optimizer'], ['初始学习率', 'learningRate', 'lr0'],
    ['最终学习率比例', 'finalLearningRate', 'lrf'], ['动量', null, 'momentum'], ['权重衰减', null, 'weight_decay'],
  ] },
  { title: '训练规模与设备', rows: [
    ['训练轮次', 'epochs', 'epochs'], ['批次大小', 'batchSize', 'batch'], ['输入尺寸', 'imageSize', 'imgsz'],
    ['设备', 'deviceId', 'device'], ['AMP', 'amp', 'amp'], ['DataLoader 进程数', null, 'workers'],
  ] },
  { title: '复现与数据增强', rows: [
    ['随机种子', 'seed', 'seed'], ['早停耐心值', 'patience', 'patience'], ['确定性训练', null, 'deterministic'],
    ['Mosaic', null, 'mosaic'], ['MixUp', null, 'mixup'],
  ] },
]
const versions = computed(() => Object.entries(props.task.runtime?.versions ?? {}))
const format = (value?: string | number | boolean) =>
  typeof value === 'boolean' ? value ? '启用' : '关闭' : value ?? '—'
</script>

<template>
  <section class="config-panel" aria-labelledby="training-config-title">
    <header class="config-header">
      <div>
        <h2 id="training-config-title">训练超参</h2>
        <p>查看本次提交配置与训练器报告的实际参数。调整参数后可另建任务。</p>
      </div>
      <button class="button primary" type="button" @click="emit('retrain', task.config)">使用此配置新建训练</button>
    </header>
    <div class="config-grid">
      <article v-for="group in groups" :key="group.title">
        <h3>{{ group.title }}</h3>
        <table>
          <thead><tr><th scope="col">参数</th><th scope="col">提交配置</th><th scope="col">实际生效</th></tr></thead>
          <tbody><tr v-for="[label, config, actual] in group.rows" :key="actual">
            <th scope="row">{{ label }}</th>
            <td>{{ format(config ? task.config[config] : undefined) }}</td>
            <td>{{ format(task.runtime?.arguments?.[actual]) }}</td>
          </tr></tbody>
        </table>
      </article>
      <article>
        <h3>运行环境与复现记录</h3>
        <dl>
          <div><dt>基础模型</dt><dd>{{ task.modelName }}</dd></div>
          <div><dt>数据集</dt><dd>{{ task.datasetName }}</dd></div>
          <div><dt>数据增强策略</dt><dd>{{ task.config.augmentation === 'standard' ? '标准增强' : task.config.augmentation }}</dd></div>
          <div><dt>数据快照</dt><dd>{{ task.snapshotDigest ?? '—' }}</dd></div>
          <div v-for="[name, version] in versions" :key="name"><dt>{{ name }}</dt><dd>{{ version }}</dd></div>
        </dl>
        <p v-if="!task.runtime?.arguments">该任务暂无训练器实际参数记录。</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.config-panel { display: grid; gap: 12px; min-width: 0; }
.config-header, article { padding: 14px; border: 1px solid var(--line); border-radius: 5px; background: var(--surface); min-width: 0; }
.config-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; }
h2, h3, p, dl { margin: 0; }
h2 { font-size: 16px; } h3 { margin-bottom: 10px; font-size: 14px; }
p { margin-top: 4px; color: var(--muted); font-size: 12px; }
.config-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 10px; }
table { width: 100%; border-collapse: collapse; text-align: left; font-size: 12px; }
th, td { padding: 7px 8px; border-bottom: 1px solid var(--line); }
thead { background: var(--soft); color: var(--muted); }
tbody th { font-weight: 400; }
td, dd { font-family: Consolas, "Microsoft YaHei UI", monospace; }
dl div { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--line); font-size: 12px; }
dt { color: var(--muted); }
dd { margin: 0; overflow-wrap: anywhere; }
</style>
