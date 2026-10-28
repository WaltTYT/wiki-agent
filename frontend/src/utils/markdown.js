/**
 * 极简 Markdown 渲染（零依赖）。
 * 顺序很重要：先整体转义 HTML，再做少量替换，因此不存在 XSS 注入面。
 * 需要更完整语法时再换 markdown-it + dompurify（plan §2.2 的可选项）。
 */

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

export function renderMarkdown(raw) {
  if (!raw) return ''
  let text = escapeHtml(String(raw))

  // 代码块
  text = text.replace(/```([\s\S]*?)```/g, (_m, code) => `<pre class="code">${code.replace(/^\n/, '')}</pre>`)
  // 行内代码
  text = text.replace(/`([^`\n]+)`/g, '<code>$1</code>')
  // 加粗 / 斜体
  text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  // 标题
  text = text.replace(/^###\s+(.*)$/gm, '<h4>$1</h4>')
  text = text.replace(/^##\s+(.*)$/gm, '<h3>$1</h3>')
  // 无序列表
  text = text.replace(/^[-*]\s+(.*)$/gm, '<li>$1</li>')
  text = text.replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, '<ul>$1</ul>')
  // 链接
  text = text.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
  // 段落换行（不在 pre 里的）
  text = text.replace(/\n{2,}/g, '<br><br>').replace(/\n/g, '<br>')
  text = text.replace(/<\/pre><br*>\s*/g, '</pre>')
  return text
}