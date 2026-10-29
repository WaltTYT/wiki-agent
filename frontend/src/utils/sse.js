/**
 * SSE 流式解析：fetch + ReadableStream。
 *
 * 关键坑（V1 最容易翻车的地方）：网络 chunk 的边界和 SSE 帧边界不对齐，
 * 一帧可能被拆到两次 read() 里，也可能两次 read 才凑齐一帧。
 * 所以必须自己维护 buffer，只在遇到空行（\n\n）时才真正解析。
 */

function parseFrame(block) {
  const dataLines = []
  for (const line of block.split(/\r?\n/)) {
    const s = line.trimEnd()
    if (s.startsWith('data:')) dataLines.push(s.slice(5).trimStart())
    else if (s.startsWith(':')) continue // 注释/心跳帧，忽略
  }
  if (!dataLines.length) return null
  try {
    return JSON.parse(dataLines.join('\n'))
  } catch {
    return { type: 'error', message: '无法解析的帧: ' + dataLines.join(' ').slice(0, 120) }
  }
}

/**
 * @param {string} question
 * @param {object} handlers { model, onSources(refs), onTrace(trace), onToken(text), onError(msg), onDone(), signal }
 */
export async function streamChat(question, handlers = {}) {
  const { onSources, onTrace, onToken, onError, onDone, signal, model } = handlers
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(model ? { question, model } : { question }),
    signal,
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${detail.slice(0, 200)}`)
  }
  if (!res.body) throw new Error('当前浏览器不支持 ReadableStream')

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const emit = (payload) => {
    if (!payload) return
    if (payload.type === 'sources') onSources && onSources(payload.refs || [])
    else if (payload.type === 'trace') onTrace && onTrace(payload)
    else if (payload.type === 'token') onToken && onToken(payload.text || '')
    else if (payload.type === 'error') onError && onError(payload.message || '未知错误')
    else if (payload.type === 'done') onDone && onDone()
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      emit(parseFrame(block))
    }
  }
  buffer += decoder.decode()
  if (buffer.trim()) emit(parseFrame(buffer)) // 收尾：最后一帧可能没有结尾空行
}