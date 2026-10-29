<script setup>
import { computed } from 'vue'
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

    <div class="side-foot">V2.0 · 自我纠错 RAG</div>
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
.side-foot { padding: 8px 8px 0; font-size: 11px; color: #b3b8bf; }
@media (max-width: 900px) {
  .sidebar { width: 220px; }
}
</style>
