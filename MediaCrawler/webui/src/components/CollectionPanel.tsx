import { useState } from 'react'

export type CollectionPlan = {queries: string[]; posts_per_query: number; comment_posts: number; comments_per_post: number; seconds: number}
export type CollectionJob = {id: string; question: string; status: string; error: string | null; plan: CollectionPlan;
  progress: {local_preview: {query: string; local_posts: number | null}[]; source_ids: string[];
    branches: {task_id: string; query: string | null; stage: string; status: string; posts?: number; comments?: number}[]}}
export const collectionActive = (job: CollectionJob) => ['running', 'waiting_login', 'importing', 'answering'].includes(job.status)
const labels: Record<string, string> = {proposed: '等待确认', running: '采集中', waiting_login: '等待扫码登录', importing: '正在导入', answering: '正在回答', completed: '已完成', partial: '部分完成', failed: '失败', cancelled: '已取消', interrupted: '服务重启中断'}
const errors: Record<string, string> = {cancelled: '用户已取消', collection_timeout: '达到总时限，已停止', collection_login_timeout: '总时限内未完成登录，已停止', login_incomplete: '登录尚未完成，浏览器或爬虫已退出', collection_no_data: '本次未取得可导入文件', crawler_start_failed: '爬虫未能启动', crawler_budget_violation: '采集结果超过批准上限，已停止后续步骤', crawler_stopped: '爬虫已停止', service_restarted: '服务重启导致中断'}

export function CollectionPanel({job, execute, cancel, disabled}: {job: CollectionJob; execute: (plan: CollectionPlan) => void; cancel: () => void; disabled: boolean}) {
  const [plan, setPlan] = useState(job.plan)
  const [queries, setQueries] = useState(job.plan.queries.join('\n'))
  return <article id={'collection-' + job.id} className="border rounded p-4 space-y-3" aria-label="在线采集计划">
    <h2 className="font-semibold">在线采集 · {labels[job.status] || job.status}</h2>
    <p>{job.question}</p>
    {job.status === 'proposed' ? <>
      <p className="text-sm">平台：百度贴吧。确认后打开浏览器，必要时扫码登录。先采帖子，再为字面匹配的候选帖子补采评论。最多 3 个查询，不自动扩展别名。</p>
      <p>助手生成的查询词：{queries.split('\n').filter(Boolean).join('；')}</p>
      <details><summary className="cursor-pointer underline">调整查询词（可选）</summary>
        <label className="block mt-2">查询词（每行一个）<textarea aria-label="采集查询词" className="border rounded w-full p-2 bg-transparent" value={queries} onChange={e => setQueries(e.target.value)} /></label>
      </details>
      <div className="flex flex-wrap gap-3">{([
        ['posts_per_query', '每个查询最多帖子数', 1, 20], ['comment_posts', '补采评论的帖子数', 0, 5],
        ['comments_per_post', '每帖最多一级评论数', 1, 20], ['seconds', '总时限（秒，含回答）', 30, 300],
      ] as const).map(([key, label, min, max]) => <label key={key}>{label}<input className="block border rounded p-2 w-24 bg-transparent" type="number" min={min} max={max} value={plan[key]} onChange={e => setPlan({...plan, [key]: Number(e.target.value)})} /></label>)}</div>
      <p className="text-sm">初始查询的本地命中：{job.progress.local_preview.map(p => `${p.query}：${p.local_posts === null ? '尚无可检索结果，或本地查询未成功' : p.local_posts + ' 帖'}`).join('；')}。修改查询后以实际执行为准；本地内容已足够时可取消计划，直接发送问题。</p>
      <button disabled={disabled} className="border rounded px-3 py-2" onClick={() => execute({...plan, queries: queries.split('\n').map(q => q.trim()).filter(Boolean)})}>确认计划并采集</button>
    </> : <p>查询：{job.plan.queries.join('；')} · 已导入 {job.progress.source_ids.length} 个文件来源</p>}
    {job.status === 'waiting_login' && <p role="status">请在打开的贴吧浏览器窗口完成登录；未自动弹出时请手动打开登录入口。完成后自动继续，等待计入总时限。</p>}
    {job.progress.branches.map(b => <p key={b.task_id} className="text-sm">{b.stage === 'posts' ? `搜索：${b.query}` : '补采评论'} · {b.status}{b.posts !== undefined ? ` · ${b.posts} 帖 / ${b.comments} 评论` : ''}</p>)}
    {job.error && <p role="alert">本次采集未完整结束：{errors[job.error] || job.error}。已导入内容仍保留。</p>}
    {(job.status === 'proposed' || collectionActive(job)) && <button disabled={disabled} className="border rounded px-3 py-2 ml-2" onClick={cancel}>取消采集</button>}
  </article>
}
