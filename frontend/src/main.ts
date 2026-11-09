import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import VueKonva from 'vue-konva'
import App from './App.vue'
import './style.css'

// App renders both route views so the data list can retain its filters and scroll state.
const RouteTarget = { render: () => null }
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/datasets', name: 'datasets', component: RouteTarget },
    { path: '/datasets/:id/annotate', name: 'annotation', component: RouteTarget },
    { path: '/:pathMatch(.*)*', redirect: '/datasets' },
  ],
})

createApp(App).use(router).use(VueKonva).mount('#app')
