import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

const app = createApp(App)

// Pinia 在校勘链路里承担跨页状态传递（首页提交 -> 校勘页渲染），必须在使用前装上
app.use(createPinia())
app.use(router)

app.mount('#app')
