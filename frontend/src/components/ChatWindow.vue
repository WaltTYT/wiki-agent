<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import ChatSidebar from './ChatSidebar.vue'
import MessageBubble from './MessageBubble.vue'
import logoUrl from '../assets/fount-logo.png'
import { streamChat } from '../utils/sse.js'

const MODEL_KEY = 'wiki-agent.model'
const SESSIONS_KEY = 'wiki-agent.sessions'

// current 里始终放「正在看的那个会话对象」：新建时是尚未落盘的草稿，
// 发出第一条消息后才进入 sessions（侧边栏列表）。
const current = ref(blankSession())
const sessions = ref([])
const input = ref('')
const busy = ref(false)
const listEl = ref(null)

const models = ref([])
const groups = ref([]) // 按 provider 分组（千问 / 智谱）
const currentModel = ref('')
const modelError = ref('')
const pickerOpen = ref(false)
const pickerEl = ref(null)

let controller = null

const ordered = computed(() => [...sessions.value].sort((a, b) => b.updatedAt - a.updatedAt))
const activeId = computed(() => current.value.id)

function blankSession() {
  return {
    id: 's-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
    title: '',
    model: '',
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messages: [],
  }
}

async function scrollBottom() {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}

function persist() {
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.value))
  } catch {
    /* 隐私模式或配额满时保存失败，不影响当前对话 */
  }
}

function restoreSessions() {
  try {
    const raw = JSON.parse(localStorage.getItem(SESSIONS_KEY) || '[]')
    if (!Array.isArray(raw) || !raw.length) return
    sessions.value = raw
      .filter((s) => s && s.id && Array.isArray(s.messages))
      .map((s) => {
        const messages = s.messages.map((m) => {
          const msg = { sources: [], trace: [], error: '', model: '', ...m, streaming: false }
          // 上次关页面时可能正在流式生成，恢复时不要留下一直闪烁的光标
          if (msg.role === 'assistant' && !msg.text && !msg.error) msg.error = '生成中断'
          return msg
        })
        return {
          id: String(s.id),
          title: String(s.title || ''),
          model: typeof s.model === 'string' ? s.model : '',
          createdAt: Number(s.createdAt) || Date.now(),
          updatedAt: Number(s.updatedAt) || Number(s.createdAt) || Date.now(),
          messages,
        }
      })
    current.value = [...sessions.value].sort((a, b) => b.updatedAt - a.updatedAt)[0]
  } catch {
    sessions.value = []
  }
}

// 拉取后端白名单，而不是在前端硬编码模型名
async function loadModels() {
  try {
    const res = await fetch('/api/models')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    models.value = data.models || []
    groups.value = data.groups || []
    const saved = localStorage.getItem(MODEL_KEY)
    const preferred = [saved, current.value.model].find((m) => m && models.value.includes(m))
    currentModel.value = preferred || data.default || models.value[0] || ''
  } catch (e) {
    modelError.value = '模型列表加载失败：' + (e.message || e)
  }
}

function togglePicker() {
  if (busy.value) return
  pickerOpen.value = !pickerOpen.value
}

function pickModel(m) {
  currentModel.value = m
  current.value.model = m
  pickerOpen.value = false
  try {
    localStorage.setItem(MODEL_KEY, m)
  } catch {
    /* 隐私模式下 localStorage 会抛错，忽略即可 */
  }
}

function onDocClick(e) {
  if (pickerOpen.value && pickerEl.value && !pickerEl.value.contains(e.target)) pickerOpen.value = false
}

async function ask(question) {
  const q = (question || input.value).trim()
  if (!q || busy.value) return
  input.value = ''
  busy.value = true
  pickerOpen.value = false
  controller = new AbortController()

  const session = current.value
  const usedModel = currentModel.value
  session.messages.push({ role: 'user', text: q })
  session.messages.push({ role: 'assistant', text: '', sources: [], trace: [], error: '', streaming: true, model: usedModel })
  if (!session.title) session.title = q.replace(/\s+/g, ' ').slice(0, 30)
  session.model = usedModel
  session.updatedAt = Date.now()
  if (!sessions.value.some((s) => s.id === session.id)) sessions.value.push(session)
  persist()
  // 关键：必须取回数组里的「响应式代理」来改。
  // 若直接持有 push 之前的原始对象（const reply = {...}; push(reply)），
  // 改 reply.text 不会触发渲染 —— Vue 3 的 raw/proxy 陷阱，
  // 表现为「SSE 帧都收到了，界面却一直空白」。已用 node + vue 实测确认。
  const reply = session.messages[session.messages.length - 1]
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
    session.updatedAt = Date.now()
    persist()
    await scrollBottom()
  }
}

function stop() {
  if (controller) controller.abort()
}

function newChat() {
  if (busy.value) stop()
  current.value = blankSession()
  input.value = ''
  pickerOpen.value = false
}

function selectSession(id) {
  if (busy.value) stop()
  const s = sessions.value.find((x) => x.id === id)
  if (!s) return
  current.value = s
  input.value = ''
  if (s.model && models.value.includes(s.model)) currentModel.value = s.model
  scrollBottom()
}

function removeSession(id) {
  const idx = sessions.value.findIndex((s) => s.id === id)
  if (idx === -1) return
  if (busy.value && current.value.id === id) stop()
  sessions.value.splice(idx, 1)
  if (current.value.id === id) {
    current.value = ordered.value[0] || blankSession()
    scrollBottom()
  }
  persist()
}

onMounted(() => {
  restoreSessions()
  loadModels()
  document.addEventListener('click', onDocClick)
})
onBeforeUnmount(() => {
  stop()
  document.removeEventListener('click', onDocClick)
})
</script>

<template>
  <div class="shell">
    <ChatSidebar
      :sessions="ordered"
      :active-id="activeId"
      @new-chat="newChat"
      @select="selectSession"
      @remove="removeSession"
    />

    <section class="main">
      <main ref="listEl" class="thread-scroll">
        <div class="thread">
          <div v-if="!current.messages.length" class="empty">
            <img class="empty-logo" :src="logoUrl" alt="Fount" />
            <h2>你好，有什么我能帮你的吗？</h2>
            <p>答案只来自已入库的文档，检索不到会直说，不会编。</p>
          </div>
          <MessageBubble v-for="(m, i) in current.messages" :key="i" :msg="m" />
        </div>
      </main>

      <footer class="composer-wrap">
        <div v-if="modelError" class="model-err">{{ modelError }}</div>
        <div class="composer">
          <textarea
            v-model="input"
            :disabled="busy"
            rows="2"
            placeholder="给 Fount 发送消息"
            @keydown.enter.exact.prevent="ask()"
          />

          <div class="composer-bar">
            <span class="hint">Enter 发送 / Shift+Enter 换行</span>
            <div class="bar-right">
              <div ref="pickerEl" class="model-wrap">
                <button
                  class="model-btn"
                  type="button"
                  :disabled="busy"
                  title="切换模型"
                  @click="togglePicker"
                >
                  <span class="model-dot" />
                  <span class="model-name">{{ currentModel || '选择模型' }}</span>
                  <svg class="chev" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="m5 6.5 3 3 3-3" />
                  </svg>
                </button>

                <div v-if="pickerOpen" class="picker">
                  <div class="picker-head">内置模型</div>
                  <div class="picker-body">
                    <template v-if="groups.length">
                      <div v-for="g in groups" :key="g.id" class="pick-group">
                        <div class="pick-label">{{ g.label }}</div>
                        <button
                          v-for="m in g.models"
                          :key="g.id + '-' + m"
                          type="button"
                          class="pick-item"
                          :class="{ active: m === currentModel }"
                          @click="pickModel(m)"
                        >
                          <span class="pick-badge">{{ (m[0] || '?').toUpperCase() }}</span>
                          <span class="pick-name">{{ m }}</span>
                          <svg v-if="m === currentModel" class="check" viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                            <path d="m3.5 8.5 2.8 2.8 6.4-6.4" />
                          </svg>
                        </button>
                      </div>
                    </template>
                    <template v-else>
                      <button
                        v-for="m in models"
                        :key="m"
                        type="button"
                        class="pick-item"
                        :class="{ active: m === currentModel }"
                        @click="pickModel(m)"
                      >
                        <span class="pick-badge">{{ (m[0] || '?').toUpperCase() }}</span>
                        <span class="pick-name">{{ m }}</span>
                        <svg v-if="m === currentModel" class="check" viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                          <path d="m3.5 8.5 2.8 2.8 6.4-6.4" />
                        </svg>
                      </button>
                    </template>
                  </div>
                </div>
              </div>

              <button
                class="send"
                type="button"
                :class="{ stopping: busy }"
                :disabled="!busy && !input.trim()"
                :title="busy ? '停止生成' : '发送'"
                @click="busy ? stop() : ask()"
              >
                <svg v-if="busy" viewBox="0 0 16 16" width="14" height="14">
                  <rect x="4.5" y="4.5" width="7" height="7" rx="1.6" fill="currentColor" />
                </svg>
                <svg v-else viewBox="0 0 16 16" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M8 13V3.5M4 7.5 8 3.5l4 4" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.shell { display: flex; height: 100vh; background: #fff; }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.thread-scroll { flex: 1; overflow-y: auto; padding: 26px 20px 10px; }
.thread { max-width: 780px; margin: 0 auto; }

.empty { text-align: center; color: #6b7280; margin-top: 16vh; }
.empty-logo {
  display: block; width: 72px; height: 72px; margin: 0 auto 12px; object-fit: contain;
}
.empty h2 { color: #1f2328; font-size: 20px; margin: 0 0 8px; }
.empty p { margin: 0; font-size: 13.5px; }

.composer-wrap { padding: 10px 20px 20px; }
.composer {
  max-width: 780px; margin: 0 auto; padding: 10px 12px 8px;
  border: 1px solid #e3e6eb; border-radius: 16px; background: #fff;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.composer:focus-within { border-color: #b8c8f5; box-shadow: 0 4px 16px rgba(47, 111, 235, 0.08); }
.composer textarea {
  width: 100%; resize: none; padding: 4px 2px; font: inherit; line-height: 1.6;
  color: #1f2328; background: transparent; border: 0; outline: none;
}
.composer textarea::placeholder { color: #a8adb5; }
.composer-bar { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.hint { font-size: 11px; color: #b3b8bf; white-space: nowrap; }
.bar-right { display: flex; align-items: center; gap: 8px; }
.model-err { max-width: 780px; margin: 0 auto 6px; font-size: 12px; color: #c0392b; }

.model-wrap { position: relative; }
.model-btn {
  display: flex; align-items: center; gap: 6px; padding: 5px 10px;
  font: inherit; font-size: 12.5px; color: #3c4043; cursor: pointer;
  background: #fff; border: 1px solid #e3e6eb; border-radius: 999px;
}
.model-btn:hover { background: #f4f5f7; }
.model-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.model-dot { width: 7px; height: 7px; border-radius: 50%; background: #2f6feb; flex-shrink: 0; }
.model-name { max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chev { color: #9aa0a6; flex-shrink: 0; }

.picker {
  position: absolute; right: 0; bottom: calc(100% + 8px); z-index: 20;
  width: 300px; max-height: 360px; display: flex; flex-direction: column;
  background: #fff; border: 1px solid #e3e6eb; border-radius: 14px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.14);
}
.picker-head { padding: 10px 12px 2px; font-size: 12px; color: #9aa0a6; }
.picker-body { overflow-y: auto; padding: 4px 6px 8px; }
.pick-label { padding: 8px 8px 3px; font-size: 11.5px; color: #9aa0a6; }
.pick-item {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 7px 8px; font: inherit; font-size: 13px; text-align: left;
  color: #3c4043; background: transparent; border: 0; border-radius: 8px; cursor: pointer;
}
.pick-item:hover { background: #f4f5f7; }
.pick-item.active { background: #f0f4ff; color: #1f2328; }
.pick-badge {
  width: 20px; height: 20px; flex-shrink: 0; border-radius: 6px;
  background: #eef2ff; color: #2f6feb; display: grid; place-items: center;
  font-size: 11px; font-weight: 600;
}
.pick-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.check { color: #2f6feb; flex-shrink: 0; }

.send {
  display: grid; place-items: center; width: 34px; height: 34px; padding: 0;
  color: #fff; background: #2f6feb; border: 0; border-radius: 50%; cursor: pointer;
  transition: background 0.15s, opacity 0.15s;
}
.send:hover { background: #245bd0; }
.send:disabled { background: #eceef1; color: #b3b8bf; cursor: not-allowed; }
.send.stopping { background: #e9edf6; color: #2f6feb; }
.send.stopping:hover { background: #dde5f9; }

@media (max-width: 900px) {
  .thread-scroll, .composer-wrap { padding-left: 14px; padding-right: 14px; }
  .hint { display: none; }
}
</style>
