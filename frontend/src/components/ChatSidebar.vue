<script setup>
import { computed, ref } from 'vue'
import logoUrl from '../assets/fount-logo.png'

const props = defineProps({
  sessions: { type: Array, required: true }, // 已保存的会话，按 updatedAt 倒序
  activeId: { type: String, default: '' },
})
const emit = defineEmits(['new-chat', 'select', 'remove'])

// 会话按最后活跃时间分桶，和 DeepSeek 的分组习惯一致
const LABELS = ['今天', '昨天', '7 天内', '30 天内', '更早']

const groups = computed(() => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const buckets = LABELS.map(() => [])
  for (const s of props.sessions) {
    const t = new Date(s.updatedAt || s.createdAt || Date.now())
    t.setHours(0, 0, 0, 0)
    const days = Math.round((today - t) / 86400000)
    const idx = days <= 0 ? 0 : days === 1 ? 1 : days < 7 ? 2 : days < 30 ? 3 : 4
    buckets[idx].push(s)
  }
  return LABELS.map((label, i) => ({ label, items: buckets[i] })).filter((g) => g.items.length)
})

// 知识库弹窗 + 知识入库：点「知识库」拉到当前语料清单，弹窗底部再触发文件上传并重建索引
const picker = ref(null)
const kbOpen = ref(false)
const kbLoading = ref(false)
const kbError = ref('')
const kbFiles = ref([])
const kbTotalChunks = ref(0)
const ingesting = ref(false)
const ingestOk = ref(true)
const ingestMsg = ref('')
let clearTimer = 0

async function loadKb() {
  kbLoading.value = true
  kbError.value = ''
  try {
    const res = await fetch('/api/knowledge')
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`)
    kbFiles.value = body.files || []
    kbTotalChunks.value = body.total_chunks || 0
  } catch (err) {
    kbError.value = `读取失败：${err.message}`
  } finally {
    kbLoading.value = false
  }
}

function openKb() {
  kbOpen.value = true
  loadKb()
}

function closeKb() {
  kbOpen.value = false
  ingestMsg.value = ''
}

function openPicker() {
  if (!ingesting.value) picker.value?.click()
}

function fmtSize(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function extOf(name) {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1).toUpperCase() : '?'
}

// Wiki 记忆面板：展示后端沉淀的条目，并允许人工删除低质记忆
const wikiOpen = ref(false)
const wikiLoading = ref(false)
const wikiError = ref('')
const wikiEntries = ref([])
const deletingSlug = ref('')

async function loadWiki() {
  wikiLoading.value = true
  wikiError.value = ''
  try {
    const res = await fetch('/api/wiki')
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`)
    wikiEntries.value = body.entries || []
  } catch (err) {
    wikiError.value = `读取失败：${err.message}`
  } finally {
    wikiLoading.value = false
  }
}

function openWiki() {
  wikiOpen.value = true
  loadWiki()
}

function closeWiki() {
  wikiOpen.value = false
}

async function removeWiki(slug) {
  if (deletingSlug.value) return
  deletingSlug.value = slug
  try {
    const res = await fetch(`/api/wiki/${encodeURIComponent(slug)}`, { method: 'DELETE' })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail || `HTTP ${res.status}`)
    }
    wikiEntries.value = wikiEntries.value.filter((e) => e.slug !== slug)
  } catch (err) {
    wikiError.value = `删除失败：${err.message}`
  } finally {
    deletingSlug.value = ''
  }
}

function shortDate(s) {
  return (s || '').slice(0, 10)
}

async function onPick(e) {
  const files = Array.from(e.target.files || [])
  e.target.value = '' // 清空后才能再次选同一个文件
  if (!files.length || ingesting.value) return

  ingesting.value = true
  ingestOk.value = true
  ingestMsg.value = `正在上传并入库 ${files.length} 个文件…`
  try {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    const res = await fetch('/api/ingest/upload', { method: 'POST', body: fd })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`)
    ingestMsg.value = `已入库 ${body.uploaded.length} 个文件 / ${body.chunks} 个片段（共 ${body.total}）`
    if (kbOpen.value) await loadKb()
  } catch (err) {
    ingestOk.value = false
    ingestMsg.value = `入库失败：${err.message}`
  } finally {
    ingesting.value = false
    clearTimeout(clearTimer)
    clearTimer = setTimeout(() => (ingestMsg.value = ''), 8000)
  }
}
</script>

<template>
  <aside class="sidebar">
    <div class="side-brand">
      <img class="logo" :src="logoUrl" alt="Fount" />
      <div class="titles">
        <b>Fount</b>
        <span>知源 · 知识库问答</span>
      </div>
    </div>

    <button class="new-chat" type="button" @click="emit('new-chat')">
      <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <path d="M8 3.5v9M3.5 8h9" />
      </svg>
      新建对话
    </button>

    <div class="side-list">
      <p v-if="!sessions.length" class="side-empty">还没有对话记录</p>
      <div v-for="g in groups" :key="g.label" class="group">
        <div class="group-label">{{ g.label }}</div>
        <div
          v-for="s in g.items"
          :key="s.id"
          class="item"
          :class="{ active: s.id === activeId }"
          @click="emit('select', s.id)"
        >
          <span class="item-title">{{ s.title || '新对话' }}</span>
          <button class="item-del" type="button" title="删除对话" @click.stop="emit('remove', s.id)">
            <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 5.5h10M6.5 5.5V4h3V5.5M4.8 5.5l.5 7h5.4l.5-7" />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <div class="side-foot">
      <button class="kb-btn" type="button" @click="openWiki">
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M8 2.8c-1.9-1.1-4.2-1.1-5.3-.6v9.3c1.1-.5 3.4-.5 5.3.6" />
          <path d="M8 2.8c1.9-1.1 4.2-1.1 5.3-.6v9.3c-1.1-.5-3.4-.5-5.3.6" />
          <path d="M8 2.8v9.3" />
        </svg>
        Wiki 记忆
      </button>
      <button class="kb-btn" type="button" @click="openKb">
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3.6 12.6V4.3c0-.6.5-1.1 1.1-1.1h7.7v9.4" />
          <path d="M3.6 12.6c0 .7.5 1.2 1.2 1.2h8.2" />
          <path d="M6.4 6.6h3.3M6.4 9.2h3.3" />
        </svg>
        知识库
      </button>
      <input
        ref="picker"
        class="picker"
        type="file"
        accept=".pdf,.md,.txt"
        multiple
        @change="onPick"
      />
      <span class="version">V3.0 · Wiki 记忆</span>
    </div>

    <Teleport to="body">
      <div v-if="wikiOpen" class="kb-mask" @click.self="closeWiki">
        <section class="kb-panel" role="dialog" aria-modal="true" aria-label="Wiki 记忆">
          <header class="kb-head">
            <b>Wiki 记忆</b>
            <button class="kb-close" type="button" title="关闭" @click="closeWiki">
              <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
                <path d="M4 4l8 8M12 4l-8 8" />
              </svg>
            </button>
          </header>

          <p v-if="!wikiLoading && !wikiError" class="kb-sum">
            共 {{ wikiEntries.length }} 条沉淀记忆 · 命中后直接作答，不再检索文档
          </p>
          <p v-if="wikiError" class="kb-empty bad wrap">{{ wikiError }}</p>

          <div class="kb-list">
            <p v-if="wikiLoading" class="kb-empty">正在读取…</p>
            <p v-else-if="!wikiEntries.length" class="kb-empty">
             还没有沉淀记忆。问一个资料里能明确回答的问题，系统会自动判断是否值得记住。
            </p>
            <template v-else>
              <div v-for="e in wikiEntries" :key="e.slug" class="wiki-item">
                <div class="wiki-body">
                  <div class="wiki-title">{{ e.title }}</div>
                  <div class="wiki-q">{{ e.question }}</div>
                  <div v-if="e.sources && e.sources.length" class="wiki-src">
                    <span v-for="(s, i) in e.sources" :key="i" class="wiki-chip">{{ s }}</span>
                  </div>
                </div>
                <div class="wiki-side">
                  <span class="wiki-date">{{ shortDate(e.created_at) }}</span>
                  <button
                    class="item-del show"
                    type="button"
                    title="删除这条记忆"
                    :disabled="deletingSlug === e.slug"
                    @click="removeWiki(e.slug)"
                  >
                    <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M3 5.5h10M6.5 5.5V4h3V5.5M4.8 5.5l.5 7h5.4l.5-7" />
                    </svg>
                  </button>
                </div>
              </div>
            </template>
          </div>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="kbOpen" class="kb-mask" @click.self="closeKb">
        <section class="kb-panel" role="dialog" aria-modal="true" aria-label="知识库">
          <header class="kb-head">
            <b>知识库</b>
            <button class="kb-close" type="button" title="关闭" @click="closeKb">
              <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
                <path d="M4 4l8 8M12 4l-8 8" />
              </svg>
            </button>
          </header>

          <p v-if="!kbLoading && !kbError" class="kb-sum">
            共 {{ kbFiles.length }} 个文件 · {{ kbTotalChunks }} 个片段
          </p>

          <div class="kb-list">
            <p v-if="kbLoading" class="kb-empty">正在读取…</p>
            <p v-else-if="kbError" class="kb-empty bad">{{ kbError }}</p>
            <p v-else-if="!kbFiles.length" class="kb-empty">
              知识库还是空的，点下面的「知识入库」上传 PDF / MD
            </p>
            <template v-else>
              <div v-for="f in kbFiles" :key="f.name" class="kb-item">
                <span class="kb-badge">{{ extOf(f.name) }}</span>
                <span class="kb-name" :title="f.name">{{ f.name }}</span>
                <span class="kb-meta">{{ fmtSize(f.size) }} · {{ f.chunks }} 片段</span>
              </div>
            </template>
          </div>

          <footer class="kb-foot">
            <button class="ingest" type="button" :disabled="ingesting" @click="openPicker">
              <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M8 10V3.4M5.2 6.2 8 3.4l2.8 2.8" />
                <path d="M3.6 11v1.9h8.8V11" />
              </svg>
              {{ ingesting ? '入库中…' : '知识入库' }}
            </button>
            <p v-if="ingestMsg" class="ingest-msg" :class="{ bad: !ingestOk }">{{ ingestMsg }}</p>
          </footer>
        </section>
      </div>
    </Teleport>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 264px; flex-shrink: 0; display: flex; flex-direction: column;
  padding: 14px 10px 10px; background: #f7f8fa; border-right: 1px solid #ececf0;
}
.side-brand { display: flex; align-items: center; gap: 9px; padding: 2px 6px 14px; }
.logo { width: 34px; height: 34px; flex-shrink: 0; object-fit: contain; display: block; }
.titles { display: flex; flex-direction: column; line-height: 1.25; }
.titles b { font-size: 14px; }
.titles span { font-size: 11px; color: #9aa0a6; }
.new-chat {
  display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%;
  padding: 9px 10px; font: inherit; font-size: 13.5px; color: #1f2328; cursor: pointer;
  background: #fff; border: 1px solid #e3e6eb; border-radius: 999px;
}
.new-chat:hover { border-color: #2f6feb; color: #2f6feb; }
.side-list { flex: 1; overflow-y: auto; margin-top: 8px; }
.side-empty { margin: 18px 8px; font-size: 12px; color: #9aa0a6; }
.group-label { padding: 12px 8px 4px; font-size: 11.5px; color: #9aa0a6; }
.item {
  display: flex; align-items: center; gap: 6px; padding: 7px 8px; margin-bottom: 1px;
  border-radius: 8px; font-size: 13px; color: #3c4043; cursor: pointer;
}
.item:hover { background: #eef0f3; }
.item.active { background: #e6eaf2; color: #1f2328; font-weight: 500; }
.item-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.item-del {
  display: grid; place-items: center; width: 22px; height: 22px; padding: 0; flex-shrink: 0;
  color: #9aa0a6; background: transparent; border: 0; border-radius: 6px; cursor: pointer; opacity: 0;
}
.item:hover .item-del, .item.active .item-del { opacity: 1; }
.item-del:hover { color: #c0392b; background: #fff0f0; }
.side-foot {
  display: flex; flex-direction: column; gap: 6px;
  margin-top: 8px; padding: 9px 6px 0; border-top: 1px solid #ececf0;
}
.kb-btn {
  display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%;
  padding: 8px 10px; font: inherit; font-size: 12.5px; color: #3c4043; cursor: pointer;
  background: #fff; border: 1px solid #e3e6eb; border-radius: 8px;
}
.kb-btn:hover { border-color: #2f6feb; color: #2f6feb; }
.picker { display: none; }
.version { font-size: 11px; color: #b3b8bf; }

/* 知识库弹窗 */
.kb-mask {
  position: fixed; inset: 0; z-index: 50; display: grid; place-items: center;
  padding: 24px; background: rgba(17, 24, 32, 0.36);
}
.kb-panel {
  display: flex; flex-direction: column; width: min(560px, 100%);
  max-height: min(72vh, 620px); overflow: hidden;
  background: #fff; border-radius: 14px; box-shadow: 0 18px 48px rgba(17, 24, 39, 0.18);
}
.kb-head { display: flex; align-items: center; justify-content: space-between; padding: 15px 18px 8px; }
.kb-head b { font-size: 15px; color: #1f2328; }
.kb-close {
  display: grid; place-items: center; width: 26px; height: 26px; padding: 0;
  color: #8a9098; background: transparent; border: 0; border-radius: 6px; cursor: pointer;
}
.kb-close:hover { color: #1f2328; background: #f1f3f6; }
.kb-sum { margin: 0; padding: 0 18px 10px; font-size: 12px; color: #9aa0a6; }
.kb-list { flex: 1; overflow-y: auto; padding: 2px 10px 12px; }
.kb-empty { margin: 16px 8px; font-size: 12.5px; line-height: 1.6; color: #9aa0a6; }
.kb-empty.bad { color: #c0392b; }
.kb-empty.wrap { padding: 0 18px; word-break: break-all; }

/* Wiki 记忆条目 */
.wiki-item {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px; border-radius: 9px;
}
.wiki-item:hover { background: #f6f7f9; }
.wiki-body { flex: 1; min-width: 0; }
.wiki-title { font-size: 13px; color: #1f2328; font-weight: 500; }
.wiki-q {
  margin-top: 2px; font-size: 11.5px; color: #9aa0a6;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.wiki-src { margin-top: 5px; display: flex; flex-wrap: wrap; gap: 4px; }
.wiki-chip {
  padding: 0 6px; border-radius: 5px; font-size: 10.5px;
  color: #1f7a4d; background: #eaf7ef;
}
.wiki-side { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.wiki-date { font-size: 11px; color: #b3b8bf; }
.item-del.show { opacity: 1; }
.item-del:disabled { cursor: progress; opacity: 0.4; }
.kb-item { display: flex; align-items: center; gap: 10px; padding: 9px 10px; border-radius: 9px; }
.kb-item:hover { background: #f6f7f9; }
.kb-badge {
  flex-shrink: 0; padding: 1px 6px; border-radius: 5px;
  font-size: 10.5px; color: #2f6feb; background: #eef4ff;
}
.kb-name {
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 13px; color: #3c4043;
}
.kb-meta { flex-shrink: 0; font-size: 11.5px; color: #9aa0a6; }
.kb-foot { display: flex; flex-direction: column; gap: 8px; padding: 12px 18px 16px; border-top: 1px solid #ececf0; }
.ingest {
  display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%;
  padding: 9px 10px; font: inherit; font-size: 13px; color: #1f2328; cursor: pointer;
  background: #fff; border: 1px solid #e3e6eb; border-radius: 999px;
}
.ingest:hover:not(:disabled) { border-color: #2f6feb; color: #2f6feb; }
.ingest:disabled { color: #9aa0a6; background: #fafbfc; cursor: progress; }
.ingest-msg { margin: 0; font-size: 11.5px; line-height: 1.45; color: #2e7d32; word-break: break-all; }
.ingest-msg.bad { color: #c0392b; }
@media (max-width: 900px) {
  .sidebar { width: 220px; }
}
</style>
