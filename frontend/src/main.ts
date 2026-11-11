import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import VueKonva from 'vue-konva'
import App from './App.vue'
import './style.css'

// App keeps the dataset view mounted so it can retain its filters.
const RouteTarget = { render: () => null }
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/datasets', name: 'datasets', component: RouteTarget },
    { path: '/datasets/:id/annotate', name: 'annotation', component: RouteTarget },
    { path: '/training', name: 'training', component: RouteTarget },
    { path: '/training/:taskId', name: 'training-detail', component: RouteTarget },
    { path: '/models', name: 'models', component: RouteTarget },
    { path: '/models/compare', name: 'model-compare', component: RouteTarget },
    { path: '/deployments', name: 'deployments', component: RouteTarget },
    { path: '/:pathMatch(.*)*', redirect: '/datasets' },
  ],
})

createApp(App).use(router).use(VueKonva).mount('#app')
