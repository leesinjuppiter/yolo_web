<script setup lang="ts">
defineProps<{ vendor?: 'amd' | 'intel' | 'unknown' }>()
</script>

<template>
  <svg v-if="vendor === 'amd'" class="cpu-brand" viewBox="0 0 24 24" role="img" aria-label="AMD">
    <rect width="24" height="24" rx="3" fill="#ed1c24"/>
    <path d="M5 5h14v14h-5v-5h-4l4-4V10H5zM5 11h5v8H5z" fill="white"/>
  </svg>
  <svg v-else-if="vendor === 'intel'" class="cpu-brand" viewBox="0 0 24 24" role="img" aria-label="Intel">
    <rect width="24" height="24" rx="3" fill="#0071c5"/>
    <text x="12" y="15" text-anchor="middle" fill="white" font-family="Arial, sans-serif" font-size="9" font-weight="700">intel</text>
  </svg>
  <svg v-else class="cpu-brand generic" viewBox="0 0 24 24" role="img" aria-label="CPU">
    <rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 9h6v6H9zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>
  </svg>
</template>

<style scoped>
.cpu-brand { width: 21px; height: 21px; flex-shrink: 0; }
.generic { fill: none; stroke: #4f6885; stroke-width: 1.6; }
</style>
