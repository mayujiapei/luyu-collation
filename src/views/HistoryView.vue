<template>
  <div class="history-container">
    <h2>📚 校勘记录</h2>

    <!-- 有本次会话的校勘结果时展示真实数据；阶段一无服务端持久化，
         所以这里只有"本次会话"，跨会话历史要等阶段二引入版本库。 -->
    <table v-if="hasCurrent" class="history-table">
      <thead>
        <tr>
          <th>来源</th>
          <th>字数</th>
          <th>建议</th>
          <th>已采纳</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>本次会话 · 粘贴文本</td>
          <td>{{ store.sourceText.length }} 字</td>
          <td>{{ store.items.length }} 条</td>
          <td>{{ store.acceptedItems.length }} 条</td>
          <td><button class="btn-view" @click="openCurrent">查看报告</button></td>
        </tr>
      </tbody>
    </table>

    <div v-else class="empty-state">
      <div class="empty-icon">🗂️</div>
      <p class="empty-title">暂无校勘记录</p>
      <p class="empty-text">回到首页粘贴古籍原文开始校勘，结果会出现在这里。</p>
      <button class="btn-primary" @click="goHome">去首页粘贴原文</button>
    </div>

    <p class="footnote">
      阶段一不服务端持久化，所以这里只显示**本次会话**的校勘（刷新页面会由浏览器本地草稿恢复）；
      跨会话的历史记录与版本对比属阶段二范围。
    </p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { useCollationStore } from '@/stores/collation'

const router = useRouter()
const store = useCollationStore()

const hasCurrent = computed(() => store.sourceText.length > 0)

function openCurrent() {
  router.push('/collation')
}

function goHome() {
  router.push('/')
}
</script>

<style scoped>
.history-container { padding: 40px; }
.history-table { width: 100%; border-collapse: collapse; margin-top: 20px; background: #fff; }
.history-table th, .history-table td { padding: 15px; text-align: left; border-bottom: 1px solid #eee; }
.history-table th { background: #f4f1e8; color: #555; }

.btn-view {
  background: transparent; border: 1px solid #b22222; color: #b22222;
  padding: 5px 15px; border-radius: 4px; cursor: pointer;
}
.btn-view:hover { background: #b22222; color: #fff; }

.empty-state { text-align: center; padding: 60px 20px; color: #666; }
.empty-icon { font-size: 34px; margin-bottom: 12px; }
.empty-title { font-size: 16px; color: #333; margin: 0 0 8px; }
.empty-text { font-size: 13px; color: #888; margin: 0 0 18px; }

.btn-primary {
  background: #8b1a1a; color: #fff; border: none;
  padding: 10px 26px; border-radius: 22px; cursor: pointer; font-size: 15px;
}
.btn-primary:hover { background: #6d1414; }

.footnote { margin-top: 26px; font-size: 12px; color: #999; line-height: 1.8; }
</style>
