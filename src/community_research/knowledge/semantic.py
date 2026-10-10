"""Small optional vector index; source validity and literal evidence remain authoritative."""
import json
import math
import os
from functools import lru_cache
from urllib.parse import urlparse
import httpx
from dotenv import dotenv_values
from .store import KnowledgeError, digest, encode
from .search import date, strings


@lru_cache(maxsize=2)
def _local_model(model_name, cache_dir):
    from fastembed import TextEmbedding
    # An ordinary local-only question must never trigger a model download.
    return TextEmbedding(model_name=model_name, cache_dir=cache_dir, local_files_only=True)


class Embedder:
    def __init__(self, root):
        env = {**dotenv_values(root / '.env.research'), **os.environ}
        self.backend = env.get('RESEARCH_EMBEDDING_BACKEND') or 'remote'
        self.cache_dir = str(root / '.runtime' / 'fastembed')
        self.base = (env.get('RESEARCH_EMBEDDING_BASE_URL') or '').rstrip('/')
        self.key = env.get('RESEARCH_EMBEDDING_API_KEY') or ''
        self.model = env.get('RESEARCH_EMBEDDING_MODEL') or ('BAAI/bge-small-zh-v1.5' if self.backend == 'fastembed' else '')
        self.identity = digest(encode([self.backend,self.base,self.model]).encode())

    @property
    def configured(self):
        if self.backend == 'fastembed':
            try:
                _local_model(self.model, self.cache_dir)
                return True
            except (ImportError, OSError, ValueError):
                return False
        return self.backend == 'remote' and bool(self.base and self.key and self.model)

    def vectors(self, texts):
        if self.backend == 'fastembed':
            try:
                model = _local_model(self.model, self.cache_dir)
                query = next(iter(model.query_embed(texts[0]))).tolist()
                passages = [vector.tolist() for vector in model.embed(texts[1:])] if len(texts)>1 else []
                return validate_vectors([query] + passages, len(texts))
            except (ImportError, OSError, ValueError, StopIteration):
                raise KnowledgeError('embedding_unavailable') from None
        parsed = urlparse(self.base)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname or (parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1'))):
            raise KnowledgeError('invalid_embedding_endpoint')
        try:
            with httpx.Client(timeout=12,follow_redirects=False,trust_env=False) as client:
                with client.stream('POST',self.base+'/embeddings',headers={'Authorization':'Bearer '+self.key},json={'model':self.model,'input':texts}) as response:
                    response.raise_for_status()
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw)>4_000_000: raise ValueError()
            data = sorted(json.loads(raw)['data'],key=lambda item:item['index'])
            if [item['index'] for item in data] != list(range(len(texts))): raise ValueError()
            return validate_vectors([item['embedding'] for item in data],len(texts))
        except (httpx.HTTPError,ValueError,TypeError,KeyError):
            raise KnowledgeError('embedding_unavailable') from None


def validate_vectors(vectors, count):
    if not isinstance(vectors,list) or len(vectors)!=count: raise KnowledgeError('invalid_embedding')
    width = len(vectors[0]) if vectors and isinstance(vectors[0],list) else 0
    if not 1 <= width <= 8192: raise KnowledgeError('invalid_embedding')
    for v in vectors:
        if not isinstance(v,list) or len(v)!=width or any(type(x) not in (float,int) or not math.isfinite(x) for x in v):
            raise KnowledgeError('invalid_embedding')
        norm=math.sqrt(sum(x*x for x in v))
        if not math.isfinite(norm) or not norm: raise KnowledgeError('invalid_embedding')
    return vectors


def hybrid_search(service, query, kind='post', limit=10, source_ids=None, published_from=None, published_to=None):
    if not isinstance(query,str) or not 1<=len(query.strip())<=300 or kind not in ('post','comment') or type(limit) is not int or not 1<=limit<=20:
        raise KnowledgeError('invalid_arguments')
    selected = strings([] if source_ids is None else source_ids)
    lower,upper = date(published_from) if published_from else None,date(published_to) if published_to else None
    embedder = getattr(service,'embedder',None) or Embedder(service.store.root)
    literal = service.call('search_posts' if kind=='post' else 'search_comments',{'any_terms':query.split()[:8] if all(len(t)<=80 for t in query.split()[:8]) else [query[:80]],'limit':limit,'source_ids':selected,'published_from':published_from,'published_to':published_to})
    if not embedder.configured:
        if literal['coverage'] is not None:
            literal['coverage'].update(retrieval='literal_fallback',semantic_available=False)
        return literal
    service.store.refresh()
    with service.store.connection() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS semantic_vectors(cache_key TEXT PRIMARY KEY,snapshot_id TEXT NOT NULL,model TEXT NOT NULL,vector TEXT NOT NULL)')
        conn.execute("DELETE FROM semantic_vectors WHERE snapshot_id NOT IN (SELECT o.snapshot_id FROM occurrences o JOIN sources s ON s.id=o.source_id WHERE s.status='active')")
        catalog = service._catalog(conn)
        if selected and set(selected)-{r['source_id'] for r in catalog}: raise KnowledgeError('source_unavailable')
        rows = service._latest([r for r in catalog if r['kind']==kind and (not selected or r['source_id'] in selected)])
        rows.sort(key=lambda r:r['published_at_utc'] or '',reverse=True)
        pieces = []
        for row in rows:
            published = date(row['published_at_utc']) if row['published_at_utc'] else None
            if (lower or upper) and (published is None or lower and published<lower or upper and published>upper): continue
            payload = json.loads(row['payload'])
            for field in (('title','body') if kind=='post' else ('body',)):
                body = payload.get(field) or ''
                for start in range(0,len(body),600):
                    end = min(start+800,len(body)); key = digest(encode([row['snapshot_id'],field,start,end,embedder.identity]).encode())
                    cached = conn.execute('SELECT vector FROM semantic_vectors WHERE cache_key=?',(key,)).fetchone()
                    pieces.append({'row':row,'field':field,'start':start,'end':end,'text':body[start:end],'key':key,'vector':json.loads(cached[0]) if cached else None})
        bounded = pieces[:200]
    missing = [p for p in bounded if p['vector'] is None][:32]
    # One bounded request embeds the query and at most 32 missing chunks.
    vectors = validate_vectors(embedder.vectors([query]+[p['text'] for p in missing]),1+len(missing))
    qv = vectors[0]
    with service.store.connection() as conn:
        for piece,vector in zip(missing,vectors[1:]):
            piece['vector'] = vector
            conn.execute('INSERT OR REPLACE INTO semantic_vectors VALUES(?,?,?,?)',(piece['key'],piece['row']['snapshot_id'],embedder.identity,encode(vector)))
    ranked = []
    for p in bounded:
        v = p['vector']
        if v is None: continue
        validate_vectors([qv,v],2)
        score = sum(x*y for x,y in zip(qv,v))/(math.sqrt(sum(x*x for x in qv))*math.sqrt(sum(x*x for x in v)))
        ranked.append((score,p))
    ranked.sort(key=lambda pair:pair[0],reverse=True)
    # Reserve room for semantic candidates rather than letting exact hits fill every slot.
    items = [] if literal['error'] else list(literal['items'][:max(1,limit//2)])
    seen = {i['entity_id'] for i in items}
    # Recheck after the external request: deleted sources must not regain citations.
    service.store.refresh()
    with service.store.connection() as conn:
        for score,p in ranked:
            if len(items)>=limit: break
            row=p['row']
            if row['entity_id'] in seen: continue
            try: snapshot,origins=service.store._active(conn,row['snapshot_id'])
            except KnowledgeError: continue
            origins=[o for o in origins if not selected or o['source_id'] in selected]
            if not origins: continue
            payload=json.loads(snapshot['payload']); seen.add(row['entity_id'])
            ev=service._evidence(conn,row['snapshot_id'],p['field'],p['start'],p['end'])
            items.append({'entity_id':row['entity_id'],'snapshot_id':row['snapshot_id'],'external_id':row['external_id'],'kind':kind,'published_at_utc':row['published_at_utc'],'source_ids':sorted({o['source_id'] for o in origins}),'source_url':payload['source_url'],'similarity':score,'matched_fields':[], 'snippets':[{'field':p['field'],'start':p['start'],'end':p['end'],'quote':p['text'],'evidence_id':ev}]})
        valid=[]
        for item in items:
            try:
                _,origins=service.store._active(conn,item['snapshot_id'])
                if not selected or any(o['source_id'] in selected for o in origins): valid.append(item)
            except KnowledgeError: pass
        conn.execute("DELETE FROM semantic_vectors WHERE snapshot_id NOT IN (SELECT o.snapshot_id FROM occurrences o JOIN sources s ON s.id=o.source_id WHERE s.status='active')")
    return {'schema_version':'0.1','status':'partial','items':valid,'error':None,'coverage':{'scope':'local_imported_data','returned':len(valid),'total':None,'has_more':len(pieces)>len(ranked),'retrieval':'literal_plus_vector_candidates','semantic_available':True,'embedded_chunks':len(ranked),'candidate_chunks':len(pieces),'matching':'approximate_candidates_not_confirmed_relevance'}}
