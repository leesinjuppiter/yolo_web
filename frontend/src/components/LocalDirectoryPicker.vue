<script setup lang="ts">
import { ref } from 'vue'
import { listLocalDirectories, type LocalDirectoryListing } from '../api/datasets'

const path = defineModel<string>({ required: true })
defineProps<{ disabled: boolean }>()
const open = ref(false)
const loading = ref(false)
const listing = ref<LocalDirectoryListing>()
const error = ref('')

async function browse(folder?: string) {
  if (loading.value) return
  open.value = true
  loading.value = true
  error.value = ''
  try {
    listing.value = await listLocalDirectories(folder)
  } catch (reason) {
    listing.value = undefined
    error.value = reason instanceof Error ? reason.message : '无法读取本机目录'
  } finally {
    loading.value = false
  }
}

function selectDirectory() {
  if (!listing.value?.path) return
  path.value = listing.value.path
  open.value = false
}
</script>

<template>
  <div class="local-directory-picker">
    <label for="local-dataset-directory">本机数据集目录</label>
    <div class="directory-actions">
      <input id="local-dataset-directory" v-model="path" type="text" :disabled="disabled"
        maxlength="2048" spellcheck="false" placeholder="例如 D:\datasets\coal"
        @keydown.enter.prevent="browse(path.trim() || undefined)">
      <button class="button" type="button" :disabled="disabled || loading" @click="browse(path.trim() || undefined)">浏览…</button>
    </div>
    <div v-if="open" class="directory-browser" :aria-busy="loading">
      <div class="directory-actions">
        <button class="button" type="button" :disabled="disabled || loading" @click="browse(listing?.parent ?? undefined)">
          {{ listing?.parent ? '上一级' : '磁盘列表' }}
        </button>
        <button class="button" type="button" :disabled="disabled || loading || !listing?.path" @click="selectDirectory">使用此目录</button>
        <button class="button" type="button" @click="open = false">关闭浏览</button>
      </div>
      <p v-if="loading" role="status">正在读取目录…</p>
      <p v-else-if="error" class="directory-error" role="alert">{{ error }}</p>
      <template v-else-if="listing">
        <p class="directory-path">{{ listing.path ?? '本机磁盘' }}</p>
        <ul v-if="listing.directories.length" aria-label="可选目录">
          <li v-for="entry in listing.directories" :key="entry.path">
            <button type="button" :disabled="disabled" @click="browse(entry.path)">{{ entry.name }} ›</button>
          </li>
        </ul>
        <p v-else>当前目录没有可浏览的子目录。</p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.local-directory-picker { display: grid; gap: 5px; min-width: 0; }
.directory-actions { display: flex; align-items: center; gap: 5px; }
.directory-actions input {
  flex: 1; min-width: 0; min-height: 32px; padding: 5px 7px;
  color: var(--text); background: var(--surface); border: 1px solid var(--line); border-radius: 4px; font: inherit;
}
.directory-actions button { flex: none; white-space: nowrap; }
.directory-browser { padding: 8px; border: 1px solid var(--line); border-radius: 4px; background: var(--soft); }
.directory-browser .directory-actions { flex-wrap: wrap; }
.directory-browser p { margin: 6px 0 0; overflow-wrap: anywhere; }
.directory-path { font-family: Consolas, monospace; }
.directory-error { color: var(--danger, #a9292f); }
.directory-browser ul { max-height: 150px; overflow: auto; margin: 6px 0 0; padding: 0; list-style: none; }
.directory-browser li button {
  display: block; width: 100%; padding: 5px 6px; border: 0; text-align: left; overflow-wrap: anywhere;
  background: var(--surface); color: var(--primary); font: inherit; cursor: pointer;
}
.directory-browser li button:hover { background: var(--selected, #edf2f7); }
</style>
