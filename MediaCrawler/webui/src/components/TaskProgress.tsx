import { useState } from 'react'

export type CollectionJob = {id: string; question: string; status: string; error: string | null; answer_run_id?: string | null;
  plan: {queries: string[]; posts_per_query: number; comment_posts: number; comments_per_post: number; seconds: number};
  progress: {automatic?: boolean; message?: string; strategy?: {task: string; route: string; summary: string}; candidate_limit?: number;
    planner_calls: number; source_ids: string[]; branches: {task_id: string; query: string | null; stage: string; status: string; posts?: number; comments?: number;
      yield?: {new_snapshots: number; repeated_snapshots: number; new_relevant: number; new_uncertain_or_unreviewed: number;
        requested_posts: number; elapsed_seconds: number; partial_coverage: boolean};
      exploration?: {kind: string; term: string; target: string}}[];
    candidate_review?: {counts?: Record<string, number>; items?: {snapshot_id: string; title?: string; source_url?: string | null; label: string; status: string; reason?: string; quote?: string; review_source?: string}[]};
    comment_review?: {counts?: Record<string, number>; items?: {snapshot_id: string; source_url?: string | null; label: string; status: string; reason?: string; quote?: string; review_source?: string}[]};
    answer_needs_review?: boolean;
    relation_candidates?: {term: string; kind: string; status: string; reasons: string[]; supporting_entities?: string[]}[]}}
export const collectionActive = (job: CollectionJob) => ['running','waiting_login','importing','answering'].includes(job.status)
const status: Record<string,string> = {running:'正在检索与整理…',waiting_login:'请在打开的贴吧窗口完成登录，完成后自动继续。',importing:'正在整理采集内容…',answering:'正在读取原文并回答…',completed:'已完成',partial:'部分完成',cancelled:'已停止',failed:'未完成',interrupted:'已中断',waiting_user:'需要补充信息'}
const errors: Record<string,string> = {total_timeout:'达到本轮时限',collection_timeout:'采集超时',collection_login_timeout:'等待登录超时',model_not_configured:'请先配置模型',invalid_task_strategy:'未能理解执行计划，请重试或补充目标',crawler_busy:'另一个采集任务正在运行',collection_no_data:'本轮采集没有取得可导入内容',service_restarted:'服务重启中断任务'}
const reviewLabels: Record<string,string> = {relevant:'相关', irrelevant:'无关', uncertain:'待核实'}
export function TaskProgress({job, disabled, correct}: {job: CollectionJob; cancel:()=>void; disabled:boolean;
  correct?: (snapshotId: string, label: string, reason: string) => Promise<void>}) {
  const [reasons, setReasons] = useState<Record<string,string>>({})
  const [saving, setSaving] = useState(false)
  const [correctionError, setCorrectionError] = useState('')
  const correction = (item: {snapshot_id: string; label: string; status: string}) =>
    item.status === 'reviewed' && correct && !collectionActive(job) ? <span className="block mt-1">
      <input className="border rounded p-1 mr-2 max-w-full" aria-label="更正理由" placeholder="更正理由（可选）" maxLength={300}
        value={reasons[item.snapshot_id] || ''} onChange={event => setReasons({...reasons, [item.snapshot_id]: event.target.value})} />
      {(['relevant','irrelevant','uncertain'] as const).map(label => <button key={label} className="border rounded px-2 py-1 mr-1"
        disabled={disabled || saving || item.label === label} onClick={() => {
          setSaving(true); setCorrectionError('')
          void correct(item.snapshot_id, label, reasons[item.snapshot_id] || '')
            .catch(error => setCorrectionError(String(error))).finally(() => setSaving(false))
        }}>改为{reviewLabels[label]}</button>)}
    </span> : null
  if (job.status==='proposed') return <details className="text-sm opacity-70"><summary>历史待确认计划（未执行）</summary><p>{job.question}</p><p>此计划不会自动启动。如需执行，请重新描述需求。</p></details>
  const details = <details className="text-sm"><summary className="cursor-pointer">执行详情</summary>
    <p>{job.progress.message}</p><p>查询：{job.plan.queries.filter(q=>q!=='待规划').join('；')} · 已导入 {job.progress.source_ids.length} 个来源</p>
    <p>规划调用 {job.progress.planner_calls} 次 · 候选上限 {job.progress.candidate_limit ?? '旧计划'} · 评论最多 {job.plan.comment_posts} 帖，每帖 {job.plan.comments_per_post} 条</p>
    {job.progress.branches.map(b=><p key={b.task_id}>{b.exploration ? `有限试探“${b.exploration.term}”（目标仍为“${b.exploration.target}”）` : b.query || '补充评论'} · {b.status} · {b.posts ?? 0} 帖 / {b.comments ?? 0} 评论
      {b.yield && `；新增快照 ${b.yield.new_snapshots}，重复快照 ${b.yield.repeated_snapshots}，片段初筛相关 ${b.yield.new_relevant}，待核实/未审阅 ${b.yield.new_uncertain_or_unreviewed}；请求额度 ${b.yield.requested_posts}，耗时 ${b.yield.elapsed_seconds} 秒${b.yield.partial_coverage ? '，候选统计未覆盖全部' : ''}`}</p>)}
    {job.progress.candidate_review?.counts && <p>初筛：相关 {job.progress.candidate_review.counts.relevant ?? 0} · 无关 {job.progress.candidate_review.counts.irrelevant ?? 0} · 待核实 {job.progress.candidate_review.counts.uncertain ?? 0} · 未审阅 {job.progress.candidate_review.counts.unreviewed ?? 0}</p>}
    {!!job.progress.candidate_review?.items?.length && <details><summary>逐帖筛选依据</summary>
      {job.progress.candidate_review.items.map((item, i) => <p key={i}>{item.title && <>{item.source_url && /^https?:\/\//i.test(item.source_url) ? <a className="underline" href={item.source_url} target="_blank" rel="noopener noreferrer">{item.title}</a> : item.title} · </>}{item.status === 'reviewed' ? (reviewLabels[item.label] || '待核实') : '未完成审阅'}：{item.reason || '没有可用理由'}{item.quote ? `；原文：“${item.quote.slice(0, 160)}”` : ''}{item.review_source === 'user_correction' && '（用户已更正）'}{correction(item)}</p>)}
    </details>}
    {job.progress.comment_review?.counts && <p>评论初筛：相关 {job.progress.comment_review.counts.relevant ?? 0} · 无关 {job.progress.comment_review.counts.irrelevant ?? 0} · 待核实 {job.progress.comment_review.counts.uncertain ?? 0} · 未审阅 {job.progress.comment_review.counts.unreviewed ?? 0}</p>}
    {!!job.progress.comment_review?.items?.length && <details><summary>逐条评论筛选依据</summary>
      {job.progress.comment_review.items.map((item, i) => <p key={i}>{item.status === 'reviewed' ? (reviewLabels[item.label] || '待核实') : '未完成审阅'}：{item.reason || '没有可用理由'}{item.quote ? `；评论原文：“${item.quote.slice(0, 160)}”` : ''}{item.review_source === 'user_correction' && '（用户已更正）'}{correction(item)}</p>)}
    </details>}
    {job.progress.answer_needs_review && <p>筛选依据已更正；原回答尚未重新生成，请继续提问以获得更新结论。</p>}
    {correctionError && <p role="alert">更正未保存：{correctionError}</p>}
    {!!job.progress.relation_candidates?.length && <details><summary>称呼与主题关系候选</summary>
      {job.progress.relation_candidates.map((item, i) => <p key={i}>{item.kind === 'alias' ? '候选别名' : '相关主题'}“{item.term}” · {item.supporting_entities?.length ?? 0} 个不同帖子支持 · {item.status === 'corroborated_candidate' ? '多处依据，仍待核实' : '待核实'} · {item.reasons[0]}</p>)}
    </details>}
  </details>
  if (job.answer_run_id && !collectionActive(job) && !job.error) return <div className="text-sm opacity-70">{details}</div>
  return <article className="border rounded p-3 space-y-2" aria-label="任务进度"><p>{job.question}</p>
    <p role="status">{status[job.status] || job.status}</p>
    {job.error && job.error!=='cancelled' && <p role="alert">{errors[job.error] || job.error}；已有资料仍保留。</p>}
    {details}
  </article>
}
