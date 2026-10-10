import { useEffect, useState } from 'react'

type Version = {source_url: string | null; snippets: {quote: string; evidence_id: string}[]}
type Changes = {counts: Record<string, number>; items: {entity_id: string; kind: string; change: string;
  before: Version | null; after: Version | null}[]; coverage: {total: number; returned: number; next_cursor: string | null}}
type Job = {id: string; kind: string; status: string; error: string | null;
  payload: {post_ids?: string[]; before_source_ids?: string[]};
  result: {after_source_ids?: string[]; changes?: Changes | null; changes_error?: string}}
type Request = <T>(path: string, body?: unknown, method?: string) => Promise<T>
const active = ['queued', 'reserved', 'running', 'waiting_login', 'importing']
const labels: Record<string, string> = {queued: '排队中', reserved: '正在启动', running: '正在复采',
  waiting_login: '等待扫码登录', importing: '正在导入和对比', completed: '已完成', partial: '部分完成',
  failed: '未完成', cancelled: '已取消', paused: '已暂停，需手动继续', interrupted: '服务中断'}
const errors: Record<string, string> = {queue_timeout: '排队超过本轮时限', collection_timeout: '复采超过本轮时限',
  restart_requires_resume: '服务重启后未自动联网', service_restarted: '服务中断，本次没有自动重试',
  recrawl_incomplete: '部分目标未完成复采', collection_no_data: '本次没有取得可导入内容',
  crawler_budget_violation: '采集结果超过允许范围', source_unavailable: '对比来源已失效',
  cancelled: '已停止任务', crawler_cleanup_failed: '爬虫退出未确认，请检查采集进程'}

export function RefreshQueue({request, revision}: {request: Request; revision: number}) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const [page, setPage] = useState<Record<string, Changes>>({})
  useEffect(() => {
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    async function refresh() {
      try {
        const rows = await request<Job[]>('/queue/jobs')
        if (!disposed) {
          setJobs(rows.filter(j => j.kind === 'refresh'))
          setPage(previous => Object.fromEntries(Object.entries(previous).filter(([id]) =>
            rows.some(j => j.id === id && j.result.changes && !j.result.changes_error))))
        }
      } catch (error) { if (!disposed) setNotice(String(error)) }
      finally { if (!disposed) timer = setTimeout(() => void refresh(), 3000) }
    }
    void refresh()
    return () => { disposed = true; clearTimeout(timer) }
  }, [request, revision])
  async function mutate(job: Job, operation: 'cancel' | 'resume') {
    setSaving(true)
    try {
      const result = await request<Job>('/queue/jobs/' + encodeURIComponent(job.id) + '/' + operation, {}, 'POST')
      setJobs(previous => previous.map(j => j.id === job.id ? result : j)); setNotice('')
    } catch (error) { setNotice(String(error)) }
    finally { setSaving(false) }
  }
  async function nextPage(job: Job) {
    const current = page[job.id] || job.result.changes
    if (!current?.coverage.next_cursor) return
    setSaving(true)
    try {
      const changes = await request<Changes>('/sources/compare', {before_source_ids: job.payload.before_source_ids,
        after_source_ids: job.result.after_source_ids, post_ids: job.payload.post_ids, cursor: current.coverage.next_cursor})
      setPage(previous => ({...previous, [job.id]: changes})); setNotice('')
    } catch (error) { setPage({}); setNotice(String(error)) }
    finally { setSaving(false) }
  }
  if (!jobs.length && !notice) return null
  return <details key={revision} open={revision > 0} className="border rounded p-3 space-y-3" aria-label="复采任务与队列">
    <summary className="cursor-pointer">复采任务与队列 · {jobs.filter(j => active.includes(j.status)).length} 项进行中</summary>
    <p className="text-sm opacity-70">复采按提交顺序执行，排队和登录计入总时限。新增指相对所选本地基线新出现；本次未观测不代表网站删除，也不保证取得完整评论历史。</p>
    {notice && <p role="alert">{notice}</p>}
    {jobs.map(job => {
      const changes = job.result.changes ? page[job.id] || job.result.changes : null
      return <article key={job.id} className="border rounded p-3 space-y-2">
        <p>贴吧帖子 {job.payload.post_ids?.join('、')} · <span role="status">{labels[job.status] || job.status}</span></p>
        {job.status === 'waiting_login' && <p>请在打开的贴吧窗口完成登录。</p>}
        {job.error && <p>{errors[job.error] || job.error}</p>}
        {job.result.changes_error && <p role="alert">{errors[job.result.changes_error] || job.result.changes_error}；无法读取前后对比。</p>}
        {(active.includes(job.status) || job.status === 'paused') && <button disabled={saving} className="border rounded px-2 py-1" onClick={() => void mutate(job, 'cancel')}>取消复采</button>}
        {job.status === 'paused' && <button disabled={saving} className="border rounded px-2 py-1 ml-2" onClick={() => void mutate(job, 'resume')}>继续复采</button>}
        {changes && <>
          <p>新增帖子 {changes.counts.added_posts} · 新增评论 {changes.counts.added_comments} · 帖子版本变化 {changes.counts.changed_posts} · 评论版本变化 {changes.counts.changed_comments} · 未变化 {changes.counts.unchanged} · 本次未观测 {changes.counts.not_observed}</p>
          <p className="text-sm">当前页展示 {changes.coverage.returned} 项，共 {changes.coverage.total} 项差异。</p>
          {changes.items.map(item => <details key={item.entity_id} className="text-sm">
            <summary>{item.kind === 'post' ? '帖子' : '评论'} · {({added: '相对基线新增', changed: '内容变化', not_observed: '本次未观测'} as Record<string, string>)[item.change]}</summary>
            {(['before', 'after'] as const).map(key => item[key] && <div key={key} className="border-l-2 pl-3 my-2">
              <p>{key === 'before' ? '基线快照' : '本次快照'}</p>
              {item[key]!.snippets.map(snippet => <blockquote key={snippet.evidence_id} className="whitespace-pre-wrap">{snippet.quote}</blockquote>)}
              {/^https?:\/\//i.test(item[key]!.source_url || '') && <a className="underline" href={item[key]!.source_url!} target="_blank" rel="noopener noreferrer">打开网站原帖</a>}
            </div>)}
          </details>)}
          {changes.coverage.next_cursor && <button disabled={saving} className="underline" onClick={() => void nextPage(job)}>下一页对比项</button>}
          {page[job.id] && <button disabled={saving} className="underline ml-3" onClick={() => setPage(previous => {
            const next = {...previous}; delete next[job.id]; return next
          })}>返回第一页</button>}
        </>}
      </article>
    })}
  </details>
}
