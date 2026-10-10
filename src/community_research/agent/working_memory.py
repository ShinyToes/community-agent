"""Small working messages; originals remain in the revocable knowledge store."""
from ..knowledge.store import encode


def compact_collection(context):
    progress = context['progress']
    review = progress.get('candidate_review') or {}
    return {'plan':context['plan'], 'progress':{
        'strategy':progress.get('strategy'), 'source_ids':progress.get('source_ids',[]),
        'collection_started':progress.get('collection_started',False),
        'branches':[{'query':b.get('query'),'status':b['status'],'posts':b.get('posts',0),'comments':b.get('comments',0)} for b in progress.get('branches',[])],
        'review_status':review.get('status'), 'review_counts':review.get('counts',{}),
        'review_basis':'原文快照上的独立单帖判断；可修订，不是事实证明'}}


def shrink_result(value):
    """Persist references, not a second copy of deletable source text."""
    if isinstance(value,list):
        return [shrink_result(v) for v in value]
    if isinstance(value,dict):
        return {k:shrink_result(v) for k,v in value.items() if k not in ('quote','context','post_stats','title','body','reason')}
    return value


def rebuild(base, last_pair, allowed, read_ids, usage, budget, steps):
    # IDs outside this working set can still be rediscovered through local search.
    selected = sorted(read_ids)[:100]
    selected += [i for i in sorted(allowed) if i not in read_ids][:max(0,100-len(selected))]
    state = {'working_memory':{'available_evidence_ids':selected,'read_evidence_ids':sorted(read_ids)[:100],
        'known_evidence_count':len(allowed),'listed_evidence_count':len(selected),'steps':steps[-10:],
        'usage':dict(usage),'budget':budget},
        'instruction':'完整原文仍保存在本地，早期工具正文已移出工作上下文。需要细节时用read_evidence重读以上ID，或本地检索重新发现；不可凭旧摘要补写原文。预算没有重置。单帖归属只使用该帖上下文，无关项默认不列出。'}
    return base + [{'role':'user','content':encode(state)}] + last_pair
