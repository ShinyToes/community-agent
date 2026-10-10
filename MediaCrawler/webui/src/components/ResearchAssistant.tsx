import { useEffect, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { TaskProgress, collectionActive, type CollectionJob } from './TaskProgress'
import { RefreshQueue } from './RefreshQueue'

type Paragraph = {text: string; evidence_ids: string[]}
type SourceCard = {entity_id: string; kind: string; external_id: string; title: string; source_url: string | null; evidence_ids: string[];
  post_published_at: string | null; post_reply_count: number | null; post_observed_at: string | null; post_timezone_basis: string | null;
  excerpts: {field: string; quote: string; truncated: boolean; evidence_id: string}[]}
type Run = {id: string; user_text: string; status: string; error: string | null; plan: Record<string, string> | null;
  usage: {model_calls: number; tool_calls: number}; events: {tool: string; status: string}[];
  answer_available?: boolean; answer_needs_review?: boolean; source_cards?: SourceCard[]; result_cards?: SourceCard[]; pending_cards?: SourceCard[];
  excluded_card_count?: number; screening_counts?: Record<string, number>; result_paragraphs?: Paragraph[];
  pending_paragraphs?: Paragraph[]; screening_paragraphs?: Paragraph[];
  answer: {paragraphs: Paragraph[]; limitations: string[]; outcome: string} | null}
type Piece = {quote: string; field: string; start: number; end: number; source_url: string | null}
type Evidence = {evidence: Piece; text: string; text_start: number; external_id: string; kind: string;
  context: {relation: string; status: string; items?: Piece[]}[]}
const errors: Record<string, string> = {
  invalid_model_json: '模型未返回完整有效的回答格式，纠正后仍未成功。请重试或缩小问题范围。',
  model_output_truncated: '模型输出达到长度上限，被接口截断，本轮未生成完整回答。',
  model_empty_response: '模型接口返回了空内容，请重试。',
  model_content_filtered: '模型服务未返回可用内容。',
  model_not_configured: '模型未配置。请填写项目根目录 .env.research 的接口地址、API Key 和模型名。',
  model_auth_failed: '模型认证失败，请检查 API Key。', model_timeout: '模型响应超时，请稍后重试。',
  total_timeout: '本轮达到总时限，已停止。', budget_exceeded: '本轮调用预算已用尽。',
  model_request_rejected: '模型接口拒绝请求，请检查接口地址、模型名称与兼容性。',
  model_connection_failed: '无法连接模型接口。', model_rate_limited: '模型服务限流，请稍后再试。',
  evidence_unavailable: '来源已失效，无法继续查看这段证据。', service_restarted: '服务重启中断了本轮，请重新提问。',
}
const statuses: Record<string, string> = {queued: '排队中', running: '查询中', completed: '已完成', partial: '部分完成', waiting_user: '需要补充信息', cancelled: '已取消', failed: '未完成', interrupted: '已中断'}
const goalLabels: Record<string, string> = {entity: '主题或实体', domain: '领域', question: '问题', time_range: '时间范围', constraints: '限制条件'}
async function request<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const signal = AbortSignal.timeout(body !== undefined && path.endsWith('/collections') ? 35000 : 20000)
  const response = await fetch('/api/research' + path, body === undefined && method === 'POST' ? {signal} : {
    method, signal, headers: {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body),
  })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '请求参数不合法')
  return result
}
function link(url: string | null) { return url && /^https?:\/\//i.test(url) ? url : undefined }

export function ResearchAssistant() {
  const [session, setSession] = useState(() => new URLSearchParams(location.hash.split('?')[1]).get('session') || localStorage.getItem('research-session') || '')
  const [sessions, setSessions] = useState<{id: string; created_at: string; title: string}[]>([])
  const [deleting, setDeleting] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<{id: string; title: string} | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const pickerRef = useRef<HTMLDivElement>(null)
  const mutation = useRef(false)
  const generation = useRef(0)
  const selectedSession = useRef(session)
  const [runs, setRuns] = useState<Run[]>([])
  const [text, setText] = useState('')
  const [notice, setNotice] = useState('')
  const [configured, setConfigured] = useState(false)
  const [automaticEnabled, setAutomaticEnabled] = useState(false)
  const [capabilitiesLoaded, setCapabilitiesLoaded] = useState(false)
  const [collections, setCollections] = useState<CollectionJob[]>([])
  const [sending, setSending] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [queueRevision, setQueueRevision] = useState(0)
  const refreshLock = useRef(false)
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [route, setRoute] = useState(location.hash)
  const mark = useRef<HTMLElement>(null)
  const busy = runs.find(r => ['queued', 'running'].includes(r.status))
  const collecting = collections.some(collectionActive)
  async function refreshPost(postId: string) {
    if (refreshLock.current) return
    refreshLock.current = true; setRefreshing(true)
    try {
      await request('/queue/refresh', {post_ids: [postId], request_id: crypto.randomUUID()})
      setQueueRevision(revision => revision + 1)
      setNotice('已提交复采，将与现有采集任务串行执行。')
    } catch (error) { setNotice(String(error)) }
    finally { refreshLock.current = false; setRefreshing(false) }
  }
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (!pickerRef.current?.contains(event.target as Node)) setPickerOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [])
  useEffect(() => {
    // Persist URL-selected conversations before navigating to the separate crawler surface.
    localStorage.setItem('research-session', selectedSession.current)
    const changed = () => {
      if (!location.hash.startsWith('#assistant')) return
      const id = new URLSearchParams(location.hash.split('?')[1]).get('session') ?? localStorage.getItem('research-session') ?? ''
      if (id !== selectedSession.current) {
        generation.current++; selectedSession.current = id; setSession(id); setRuns([]); setCollections([])
      }
      localStorage.setItem('research-session', id)
      setRoute(location.hash)
    }
    window.addEventListener('hashchange', changed)
    return () => window.removeEventListener('hashchange', changed)
  }, [])
  useEffect(() => {
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const refresh = async () => {
      const version = generation.current
      try {
        if (mutation.current) return
        const [config, list] = await Promise.all([request<{configured: boolean; collection_enabled?: boolean; automatic_enabled?: boolean}>('/config'), request<{id: string; created_at: string; title: string}[]>('/sessions')])
        if (disposed || version !== generation.current) return
        setConfigured(config.configured); setAutomaticEnabled(!!config.automatic_enabled); setCapabilitiesLoaded(true); setSessions(list)
        if (session && !list.some(s => s.id === session)) { select(''); return }
        if (session) {
          const result = await request<{runs: Run[]}>('/sessions/' + session)
          if (!disposed && version === generation.current) setRuns(result.runs)
          if (config.collection_enabled || config.automatic_enabled) {
            const jobs = await request<CollectionJob[]>('/sessions/' + session + '/collections')
            if (!disposed && version === generation.current) setCollections(jobs)
          }
        }
      } catch (error) { if (!disposed && version === generation.current) setNotice(String(error)) }
      finally { if (!disposed) timer = setTimeout(() => void refresh(), 1500) }
    }
    void refresh()
    return () => { disposed = true; clearTimeout(timer) }
  }, [session])
  useEffect(() => {
    const params = new URLSearchParams(route.split('?')[1])
    const run = params.get('run'), id = params.get('evidence')
    let disposed = false
    setEvidence(null)
    if (run && id) request<Evidence>(`/runs/${encodeURIComponent(run)}/evidence/${encodeURIComponent(id)}`)
      .then(data => { if (!disposed) setEvidence(data) }).catch(error => { if (!disposed) setNotice(errors[error.message] || error.message) })
    return () => { disposed = true }
  }, [route, session])
  useEffect(() => { if (evidence) mark.current?.scrollIntoView({block: 'center'}) }, [evidence])
  function select(id: string) {
    generation.current++; selectedSession.current = id
    setSession(id); setRuns([]); setCollections([]); setNotice(''); localStorage.setItem('research-session', id)
    const hash = '#assistant?session=' + id
    setRoute(hash); location.hash = hash
  }
  async function create() {
    try {
      const result = await request<{id: string}>('/sessions', {})
      setSessions(items => [{id: result.id, title: '新对话', created_at: new Date().toISOString()}, ...items])
      select(result.id); return result.id
    }
    catch (error) { setNotice(String(error)); return '' }
  }
  async function newConversation() {
    if (mutation.current) return
    mutation.current = true; generation.current++; setSending(true)
    try { await create(); setPickerOpen(false) }
    finally { mutation.current = false; setSending(false) }
  }
  async function removeSession(target: string) {
    if (!target || mutation.current || (target === session && (busy || collecting))) return
    setPickerOpen(false)
    mutation.current = true; generation.current++; setDeleting(true)
    try {
      await request('/sessions/' + target, undefined, 'DELETE')
      setSessions(items => items.filter(item => item.id !== target))
      if (selectedSession.current === target) { setText(''); select('') }
    } catch (error) { setNotice(error instanceof Error && error.message === 'session_busy' ? '会话仍在运行，请先停止并等待结束后删除。' : String(error)) }
    finally { mutation.current = false; setDeleting(false); setDeleteTarget(null) }
  }
  async function send() {
    if (!capabilitiesLoaded || !text.trim() || busy || collecting || mutation.current) return
    mutation.current = true; generation.current++; setSending(true); setNotice('')
    const question = text.trim()
    try {
      const id = selectedSession.current || await create()
      if (!id) return
      if (automaticEnabled) {
        const job = await request<CollectionJob>('/sessions/' + id + '/messages', {text: question})
        if (selectedSession.current === id) setCollections(items => [...items, job])
      } else {
        await request('/sessions/' + id + '/runs', {text: question})
        const current = await request<{runs: Run[]}>('/sessions/' + id)
        if (selectedSession.current === id) setRuns(current.runs)
      }
      if (selectedSession.current === id) setText(value => value.trim() === question ? '' : value)
    } catch (error) { setNotice(String(error)) }
    finally { mutation.current = false; setSending(false) }
  }
  async function cancelTask(id: string) {
    if (mutation.current) return
    mutation.current = true; generation.current++; setSending(true)
    const selected = selectedSession.current
    try {
      const job = await request<CollectionJob>('/collections/' + id + '/cancel', {})
      if (selectedSession.current === selected) setCollections(items => items.map(item => item.id === id ? job : item))
    } catch (error) { setNotice(String(error)) }
    finally { mutation.current = false; setSending(false) }
  }
  async function correctReview(id: string, snapshotId: string, label: string, reason: string) {
    if (mutation.current) throw new Error('当前有操作正在进行，请稍后重试')
    mutation.current = true; generation.current++; setSending(true)
    const selected = selectedSession.current
    try {
      const job = await request<CollectionJob>('/collections/' + id + '/review-corrections',
        {snapshot_id: snapshotId, label, reason})
      if (selectedSession.current === selected) {
        setCollections(items => items.map(item => item.id === id ? job : item))
        const current = await request<{runs: Run[]}>('/sessions/' + selected)
        if (selectedSession.current === selected) setRuns(current.runs)
      }
    } finally { mutation.current = false; setSending(false) }
  }
  const viewing = new URLSearchParams(route.split('?')[1]).has('evidence')
  return <section className="flex-1 overflow-auto p-4 space-y-4" aria-label="社区研究助手">
    <Dialog open={deleteTarget !== null} onOpenChange={open => { if (!open && !deleting) setDeleteTarget(null) }}>
      <DialogContent onCloseAutoFocus={event => { event.preventDefault(); inputRef.current?.focus() }}>
        <DialogTitle>删除会话</DialogTitle>
        <DialogDescription>确定删除“{deleteTarget?.title}”？该会话的提问、回答与执行记录将永久删除，采集的帖子和评论会保留。</DialogDescription>
        <div className="flex justify-end gap-3">
          <button className="border rounded px-3 py-2" disabled={deleting} onClick={() => setDeleteTarget(null)}>取消</button>
          <button className="border rounded px-3 py-2 text-red-600" disabled={deleting} onClick={() => { if (deleteTarget) void removeSession(deleteTarget.id) }}>{deleting ? '正在删除…' : '确认删除'}</button>
        </div>
      </DialogContent>
    </Dialog>
    <h1 className="text-xl font-bold">社区研究助手</h1>
    <p>直接描述你想了解的问题，我会判断需要查阅已有资料还是补充采集，并附上原文依据。需要更多内容时直接说“多找一些”。</p>
    {!capabilitiesLoaded && <p role="status">正在连接助手服务…</p>}
    {capabilitiesLoaded && !configured && <p role="status">模型未配置：请填写项目根目录 .env.research。配置保存后可直接重试。</p>}
    {notice && <p role="alert" className="text-red-500">{notice}</p>}
    {viewing ? <div className="space-y-4">
      <a className="underline" href={'#assistant?session=' + session}>← 返回刚才的对话</a>
      {evidence ? <>
        <h2>{evidence.kind === 'comment' ? '评论' : '帖子'}原文 · {evidence.external_id}</h2>
        {evidence.context.map((context, i) => <div key={i} className="border rounded p-3">
          <h3>{context.relation === 'post' ? '所属帖子' : '父评论'} · {context.status === 'resolved' ? '已关联' : '缺少本地内容'}</h3>
          {context.items?.map((piece, j) => <p key={j} className="whitespace-pre-wrap">{piece.quote}</p>)}
        </div>)}
        <article className="border rounded p-4 whitespace-pre-wrap" aria-label="引用原文">
          {evidence.text.slice(0, evidence.evidence.start - evidence.text_start)}
          <mark ref={mark}>{evidence.evidence.quote}</mark>
          {evidence.text.slice(evidence.evidence.end - evidence.text_start)}
        </article>
        {link(evidence.evidence.source_url) && <a className="underline" href={link(evidence.evidence.source_url)} target="_blank" rel="noopener noreferrer">在新标签页查看网站原帖</a>}
        <p>这里定位的是本地采集快照，原站内容可能已变化。</p>
      </> : <p>正在读取证据；若来源已失效，将显示错误。</p>}
    </div> : <>
      <div className="flex flex-wrap gap-3 items-start"><button disabled={deleting || sending} className="border rounded px-3 py-2" onClick={() => void newConversation()}>新对话</button>
        <div ref={pickerRef} className="relative w-80 max-w-full">
          <button aria-label="选择对话" aria-expanded={pickerOpen} aria-controls="session-picker" className="border rounded px-3 py-2 w-full text-left" onClick={() => setPickerOpen(open => !open)} onKeyDown={e => { if (e.key === 'Escape') setPickerOpen(false) }}>
            {sessions.find(s => s.id === session)?.title || '选择历史对话'} <span aria-hidden="true">▾</span>
          </button>
          {pickerOpen && <div id="session-picker" aria-label="历史对话列表" className="absolute z-20 mt-1 w-full max-h-72 overflow-auto border rounded shadow-lg bg-white text-slate-900" onKeyDown={e => { if (e.key === 'Escape') setPickerOpen(false) }}>
            {sessions.length === 0 && <p className="p-3 text-sm">暂无历史对话</p>}
            {sessions.map(s => <div key={s.id} data-session-id={s.id} className={'flex items-center border-b last:border-b-0 ' + (s.id === session ? 'bg-cyan-50' : '')}>
              <button disabled={deleting || sending} className="flex-1 min-w-0 text-left px-3 py-2 truncate" title={s.title} aria-current={s.id === session ? 'true' : undefined} onClick={() => { if (!mutation.current) { select(s.id); setPickerOpen(false) } }}>{s.title}</button>
              <button aria-label={'删除会话：' + s.title} title="删除这条会话" disabled={deleting || sending || (s.id === session && (!!busy || collecting))} className="shrink-0 px-3 py-2 text-xl text-red-600 disabled:opacity-40" onClick={() => { setPickerOpen(false); setDeleteTarget({id: s.id, title: s.title}) }}>×</button>
            </div>)}
          </div>}
        </div></div>
      {collections.map(job => <TaskProgress key={job.id} job={job} disabled={sending || deleting} cancel={() => void cancelTask(job.id)}
        correct={(snapshotId, label, reason) => correctReview(job.id, snapshotId, label, reason)} />)}
      {runs.map(run => <article key={run.id} className="border rounded p-4 space-y-3">
        <h2 className="font-bold">我的问题</h2><p className="whitespace-pre-wrap">{run.user_text}</p>
        <p>状态：{statuses[run.status] || run.status} · 模型调用 {run.usage.model_calls} · 工具调用 {run.usage.tool_calls}</p>
        {run.plan && <details><summary>本轮理解与计划</summary>{Object.entries(run.plan).map(([key, value]) => <p key={key}>{goalLabels[key] || key}：{value}</p>)}</details>}
        {run.events.length > 0 && <details><summary>执行记录</summary>{run.events.map((e, i) => <p key={i}>{e.tool} · {e.status}</p>)}</details>}
        {run.error && <p role="alert">{errors[run.error] || '本轮未完成：' + run.error}</p>}
        {run.answer_available === false && <p role="alert">这份回答引用的部分来源已失效，不应继续作为有效依据。</p>}
        {run.answer_needs_review && <p role="alert">筛选依据已有用户更正，原回答尚未重新生成；请继续提问以获得更新结论。</p>}
        {(run.result_paragraphs ?? run.answer?.paragraphs)?.map((paragraph, i) => <p key={i} className="whitespace-pre-wrap">{paragraph.text}</p>)}
        {run.result_paragraphs && !run.result_paragraphs.length && <p>本轮尚无已确认相关的正式结果；可查看待核实内容和筛选记录。</p>}
        {!!(run.result_cards ?? run.source_cards)?.length && <section aria-label="本次引用的帖子和评论" className="space-y-3">
          <h3 className="font-semibold">本次展示：{(run.result_cards ?? run.source_cards ?? []).filter(c => c.kind === 'post').length} 个帖子、{(run.result_cards ?? run.source_cards ?? []).filter(c => c.kind === 'comment').length} 条评论</h3>
          <p className="text-sm opacity-70">以下按独立内容列出已确认相关的引用来源；同一内容的多个片段合并展示，不代表全部检索命中。</p>
          {(run.result_cards ?? run.source_cards ?? []).map((card, index) => <article key={card.entity_id} className="border rounded p-3 space-y-2" data-source-kind={card.kind}>
            <h4 className="font-semibold">{index + 1}. {card.kind === 'post' ? '帖子' : '评论'}{card.kind === 'post' && <> · {link(card.source_url) ? <a className="underline" href={link(card.source_url)} target="_blank" rel="noopener noreferrer">{card.title}</a> : card.title}</>}</h4>
            {card.kind === 'comment' && <p>所属帖子：{link(card.source_url) ? <a className="underline" href={link(card.source_url)} target="_blank" rel="noopener noreferrer">{card.title}</a> : card.title}</p>}
            <p className="text-sm opacity-70">发帖时间：{card.post_published_at || '未采集'}（源记录时间） · 回复数（采集时）：{card.post_reply_count ?? '未采集'}</p>
            {card.excerpts.filter(e => e.field === 'body' || !card.excerpts.some(other => other.field === 'body')).slice(0, 2).map(excerpt => <blockquote key={excerpt.evidence_id} className="border-l-2 pl-3 whitespace-pre-wrap">{excerpt.quote}{excerpt.truncated ? '…' : ''}</blockquote>)}
            <div className="flex flex-wrap gap-3 text-sm">
              {link(card.source_url) && <a className="underline" href={link(card.source_url)} target="_blank" rel="noopener noreferrer">打开网站原帖 ↗</a>}
              <a className="underline" href={`#assistant?session=${session}&run=${run.id}&evidence=${card.excerpts.find(e => e.field === 'body')?.evidence_id || card.evidence_ids[0]}`}>{card.kind === 'comment' ? '查看评论原文与上下文' : '查看采集原文与引用位置'}</a>
              {automaticEnabled && card.kind === 'post' && /^\d+$/.test(card.external_id) && <button className="underline" disabled={refreshing} onClick={() => void refreshPost(card.external_id)}>复采并检查更新</button>}
            </div>
          </article>)}
        </section>}
        {!!((run.pending_cards?.length ?? 0) + (run.pending_paragraphs?.length ?? 0)) && <details><summary>待核实内容与引用来源：{run.pending_cards?.length ?? 0} 条来源</summary>
          <p className="text-sm opacity-70">这些内容尚未确认满足本轮目标，不计入正式展示数量。</p>
          {run.pending_paragraphs?.map((paragraph, i) => <p key={i} className="whitespace-pre-wrap">{paragraph.text}</p>)}
          {run.pending_cards?.map(card => <p key={card.entity_id}>{card.title} · {card.kind === 'post' ? '帖子' : '评论'}</p>)}
        </details>}
        {!!run.excluded_card_count && <details><summary>筛选记录：{run.excluded_card_count} 条引用来源被排除</summary>
          <p className="text-sm opacity-70">排除项仍保留在本地原文中，可在执行详情中核对，不计入正式结果。</p>
          {run.screening_paragraphs?.map((paragraph, i) => <p key={i} className="whitespace-pre-wrap">{paragraph.text}</p>)}
        </details>}
        {run.answer?.limitations.map((limit, i) => <p key={i} className="text-sm opacity-70">{limit}</p>)}
      </article>)}
      <textarea ref={inputRef} onFocus={() => setPickerOpen(false)} aria-label="输入问题" className="border rounded w-full p-3 bg-transparent" rows={3} maxLength={4000} value={text} onChange={e => setText(e.target.value)} placeholder="例如：收集一些热门打分帖；这款游戏最近评价如何？" />
      {automaticEnabled && <RefreshQueue request={request} revision={queueRevision} />}
      <div className="flex gap-3"><button className="border rounded px-4 py-2" disabled={!capabilitiesLoaded || !!busy || collecting || sending || deleting || !text.trim()} onClick={() => void send()}>发送</button>
        {collecting && <button className="border rounded px-4 py-2" disabled={sending || deleting} onClick={() => { const task = collections.find(collectionActive); if (task) void cancelTask(task.id) }}>停止本轮</button>}
        {busy && !collecting && <button className="border rounded px-4 py-2" onClick={() => void request('/runs/' + busy.id + '/cancel', {}).catch(error => setNotice(String(error)))}>停止本轮</button>}</div>
    </>}
  </section>
}
