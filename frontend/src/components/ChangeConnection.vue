<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { observeChanges } from '../api/changes'
import type { ConnectionState } from '../api/changes'
const state = ref<ConnectionState>('connecting')
const labels = { connecting: '正在连接变化通知', connected: '变化时自动更新', reconnecting: '通知连接中断，正在重连；可手动刷新' }
onUnmounted(observeChanges(() => {}, value => { state.value = value }))
</script>
<template><span class="change-connection" :class="state" role="status">{{ labels[state] }}</span></template>
<style scoped>
.change-connection { font-size: 12px; color: #64748b; }
.reconnecting { color: #9a5b13; }
</style>
