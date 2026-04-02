import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import './style.css'
import App from './App.vue'

import MachineTelemetryView from './views/MachineTelemetryView.vue'
import ErrorLogsView from './views/ErrorLogsView.vue'
import DiagnosticsView from './views/DiagnosticsView.vue' // <-- Import new view

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: MachineTelemetryView },
    { path: '/errors', component: ErrorLogsView },
    { path: '/diagnostics', component: DiagnosticsView } // <-- Add route
  ]
})

createApp(App).use(router).mount('#app')