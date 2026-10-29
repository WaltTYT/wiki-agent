<script setup>
import { computed } from 'vue'
import { renderMarkdown } from '../utils/markdown.js'

const props = defineProps({
  msg: { type: Object, required: true }, // { role, text, sources, trace, error, streaming }
})

const NODE_LABELS = { retrieve: '检索', grade: '判断', rewrite: '改写', generate: '生成' }

const html = computed(() => renderMarkdown(props.msg.text))
const isUser = computed(() => props.msg.role === 'user')
// V2 思考路径：把 trace 帧折叠成「检索 → 判断 → 生成」这样的短链
const tracePath = computed(() =>
  (props.msg.trace || []).map((t) => NODE_LABELS[t.node] || t.node).join(' → ')
)
const isFallback = computed(() =>
  (props.msg.trace || []).some((t) => t.node === 'generate' && t.fallback)
)
</script>

<template>
  <div class="row" :class="isUser ? 'right' : 'left'">
    <div class="bubble" :class="{ 'is-user': isUser, 'has-error': !!msg.error }">
      <div v-if="!isUser && msg.text" class="answer" v-html="html" />
      <div v-else-if="!isUser" class="answer placeholder">…</div>
      <template v-else>{{ msg.text }}</template>
      <span v-if="msg.streaming" class="caret" />

      <div v-if="!isUser && tracePath" class="trace">
        <span class="trace-label">思考路径</span>
        {{ tracePath }}
        <span v-if="isFallback" class="fallback">资料未覆盖</span>
      </div>

      <div v-if="!isUser && msg.sources && msg.sources.length" class="sources">
        <span class="sources-label">参考来源</span>
        <span v-for="(s, i) in msg.sources" :key="i" class="chip">
          {{ s.source }}<template v-if="s.page">·第{{ s.page }}页</template>
          <em v-if="typeof s.score === 'number'">{{ s.score.toFixed(2) }}</em>
        </span>
      </div>
      <div v-if="!isUser && msg.model" class="meta">{{ msg.model }}</div>
      <div v-if="msg.error" class="err">⚠ {{ msg.error }}</div>
    </div>
  </div>
</template>

<style scoped>
.row { display: flex; margin: 14px 0; }
.row.right { justify-content: flex-end; }
/* 助手回答不套气泡，直接平铺文字（DeepSeek 的阅读感更好）；用户消息保留浅灰气泡 */
.bubble {
  max-width: 100%;
  padding: 0;
  line-height: 1.75;
  word-break: break-word;
  white-space: pre-wrap;
}
.bubble.is-user {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 16px;
  background: #eff2f6;
  color: #1f2328;
}
.bubble.has-error { padding: 10px 14px; border: 1px solid #f0b4b4; border-radius: 14px; background: #fdf2f2; }
.answer { white-space: normal; }
.placeholder { color: #9aa0a6; }
:deep(pre.code) {
  background: #1f2328; color: #e6edf3; padding: 10px 12px; border-radius: 8px;
  overflow-x: auto; white-space: pre; margin: 8px 0; font-size: 13px;
}
:deep(code) { background: rgba(0, 0, 0, 0.06); padding: 1px 5px; border-radius: 4px; }
:deep(ul) { margin: 6px 0; padding-left: 22px; }
:deep(a) { color: #2f6feb; }
.caret {
  display: inline-block; width: 7px; height: 1.05em; margin-left: 2px;
  background: #2f6feb; vertical-align: -2px; animation: blink 1s steps(2, start) infinite;
}
@keyframes blink { to { visibility: hidden; } }
.trace {
  margin-top: 8px; font-size: 12px; color: #8b9199;
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
.trace-label {
  background: #eef2fb; color: #2f6feb; border-radius: 999px;
  padding: 1px 8px; font-size: 11px;
}
.fallback {
  background: #fff7e6; color: #b26a00; border: 1px solid #ffe1a8;
  border-radius: 999px; padding: 0 8px; font-size: 11px;
}
.sources { margin-top: 8px; padding-top: 8px; border-top: 1px dashed #d7dadf; font-size: 12px; }
.sources-label { color: #8b9199; margin-right: 6px; }
.chip {
  display: inline-block; background: #fff; border: 1px solid #e1e4e8; border-radius: 999px;
  padding: 1px 8px; margin: 2px 4px 2px 0; color: #444;
}
.chip em { font-style: normal; color: #9aa0a6; margin-left: 4px; }
.err { margin-top: 6px; color: #c0392b; font-size: 13px; }
.meta { margin-top: 6px; font-size: 11px; color: #9aa0a6; text-align: right; }
</style>