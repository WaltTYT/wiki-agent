<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import MessageBubble from './MessageBubble.vue'
import { streamChat } from '../utils/sse.js'

const STORE_KEY = 'wiki-agent.model'

const messages = ref([])
const input = ref('')
const busy = ref(false)
const listEl = ref(null)

const models = ref([])
const groups = ref([])   // 按 provider 分组（千问 / 智谱）
const currentModel = ref('')
const modelError = ref('')

let controller = null

const SUGGESTIONS = [
  '员工年假有几天？',
  '差旅报销需要什么材料？',
  '后端是怎么实现打字机效果的？',
]

async function scrollBottom() {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}

// 拉取后端白名单，而不是在前端硬编码模型名
async function loadModels() {
  try {
    const res = await fetch('/api/models')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    models.value = data.models || []
    groups.value = data.groups || []
    const saved = localStorage.getItem(STORE_KEY)
    currentModel.value = saved && models.value.includes(saved) ? saved : data.default || models.value[0] || ''
  } catch (e) {
    modelError.value = '模型列表加载失败：' + (e.message || e)
  }
}

function pickModel(e) {
  currentModel.value = e.target.value
  try {
    localStorage.setItem(STORE_KEY, currentModel.value)
  } catch {
    /* 隐私模式下 localStorage 会抛错，忽略即可 */
  }
}

async function ask(question) {
  const q = (question || input.value).trim()
  if (!q || busy.value) return
  input.value = ''
  busy.value = true
  controller = new AbortController()

  const usedModel = currentModel.value
  messages.value.push({ role: 'user', text: q })
  messages.value.push({ role: 'assistant', text: '', sources: [], trace: [], error: '', streaming: true, model: usedModel })
  // 关键：必须取回数组里的「响应式代理」来改。
  // 若直接持有 push 之前的原始对象（const reply = {...}; push(reply)），
  // 改 reply.text 不会触发渲染 —— Vue 3 的 raw/proxy 陷阱，
  // 表现为「SSE 帧都收到了，界面却一直空白」。已用 node + vue 实测确认。
  const reply = messages.value[messages.value.length - 1]
  await scrollBottom()

  try {
    await streamChat(q, {
      model: usedModel,
      signal: controller.signal,
      onSources: (refs) => { reply.sources = refs },
      onTrace: (t) => { reply.trace.push(t) },
      onToken: (t) => { reply.text += t; scrollBottom() },
      onError: (m) => { reply.error = m },
    })
  } catch (e) {
    if (e.name === 'AbortError') reply.error = '已停止生成'
    else reply.error = String(e.message || e)
  } finally {
    reply.streaming = false
    busy.value = false
    controller = null
    await scrollBottom()
  }
}

function stop() {
  if (controller) controller.abort()
}

function newChat() {
  if (busy.value) return
  messages.value = []
}

onMounted(loadModels)
onBeforeUnmount(stop)
</script>

<template>
  <div class="app">
    <header>
      <div class="brand">
        <b>wiki-agent</b>
        <span>V2.0 · 自我纠错 RAG</span>
      </div>
      <div class="controls">
        <label v-if="models.length" class="model">
          <span>模型</span>
          <select :value="currentModel" :disabled="busy && !messages.length" @change="pickModel">
            <!-- 有分组就按 provider 分组显示（千问 / 智谱），否则退回扁平列表 -->
            <template v-if="groups.length">
              <optgroup v-for="g in groups" :key="g.id" :label="g.label">
                <option v-for="m in g.models" :key="g.id + m" :value="m">{{ m }}</option>
              </optgroup>
            </template>
            <option v-for="m in models" v-else :key="m" :value="m">{{ m }}</option>
          </select>
        </label>
        <span v-else-if="modelError" class="model-err">{{ modelError }}</span>
        <button class="ghost" :disabled="busy" @click="newChat">新建会话</button>
      </div>
    </header>

    <main ref="listEl">
      <div v-if="!messages.length" class="empty">
        <h2>问点知识库里的东西</h2>
        <p>答案只来自已入库的文档，检索不到会直说，不会编。</p>
        <div class="sugs">
          <button v-for="s in SUGGESTIONS" :key="s" @click="ask(s)">{{ s }}</button>
        </div>
      </div>
      <MessageBubble v-for="(m, i) in messages" :key="i" :msg="m" />
    </main>

    <footer>
      <textarea
        v-model="input"
        :disabled="busy"
        rows="2"
        placeholder="Enter 发送 / Shift+Enter 换行"
        @keydown.enter.exact.prevent="ask()"
      />
      <div class="actions">
        <button v-if="busy" class="ghost" @click="stop">停止</button>
        <button class="primary" :disabled="busy || !input.trim()" @click="ask()">发送</button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.app { display: flex; flex-direction: column; height: 100vh; max-width: 860px; margin: 0 auto; }
header {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 12px 18px; border-bottom: 1px solid #e8eaee;
}
.brand { display: flex; align-items: baseline; gap: 10px; }
.brand span { color: #8b9199; font-size: 12px; }
.controls { display: flex; align-items: center; gap: 10px; }
.model { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #6b7280; }
.model select {
  font: inherit; padding: 5px 8px; border: 1px solid #d7dadf; border-radius: 8px;
  background: #fff; color: #1f2328; cursor: pointer;
}
.model select:focus { outline: none; border-color: #2f6feb; }
.model-err { font-size: 12px; color: #c0392b; }
main { flex: 1; overflow-y: auto; padding: 18px; background: #fff; }
footer { display: flex; gap: 10px; align-items: flex-end; padding: 12px 18px 18px; border-top: 1px solid #e8eaee; }
footer textarea {
  flex: 1; resize: none; padding: 10px 12px; font: inherit; line-height: 1.5;
  border: 1px solid #d7dadf; border-radius: 10px; outline: none;
}
footer textarea:focus { border-color: #2f6feb; }
.actions { display: flex; flex-direction: column; gap: 6px; }
button { cursor: pointer; border-radius: 10px; padding: 9px 16px; font: inherit; border: 1px solid transparent; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.primary { background: #2f6feb; color: #fff; }
.ghost { background: #fff; border-color: #d7dadf; color: #444; }
.empty { text-align: center; color: #6b7280; margin-top: 14vh; }
.empty h2 { color: #1f2328; margin-bottom: 6px; }
.sugs { margin-top: 18px; display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.sugs button { background: #f4f5f7; border-color: #e1e4e8; color: #333; font-size: 13px; }
</style>
