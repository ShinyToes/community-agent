"""Paired offline replay: append-only history versus the current Harness messages.

No LLM, platform, or token-price requests. Reports characters, not token savings.
Uses copies of existing local source files and leaves the product database alone.
"""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import random
import shutil
import statistics
import tempfile
import uuid
from unittest.mock import patch

from community_research.agent.runtime import Harness
from community_research.knowledge import KnowledgeStore
from community_research.knowledge.store import encode

ROOT = Path(__file__).resolve().parents[1]
FILES = ['testresult/search_contents_2026-09-18-1.json', 'testresult/search_comments_2026-09-18.json']


def characters(messages):
    return sum(len(message['content']) for message in messages)


class ReplayModel:
    def __init__(self, limit, mixed):
        self.limit, self.mixed = limit, mixed
        self.calls = 0
        self.naive = []
        self.measurements = []
        self.first_page, self.second_page = [], []
        self.original_id, self.original_quote = None, None
        self.reread_verified = False

    async def complete(self, messages):
        self.calls += 1
        if self.calls == 1:
            self.naive = copy.deepcopy(messages)
        else:
            # Use the exact same emitted action and tool output, including usage.
            # Only retaining old pairs differs from the production implementation.
            self.naive.extend(copy.deepcopy(messages[-2:]))
        self.measurements.append({'model_call': self.calls,
            'append_only_characters': characters(self.naive),
            'current_characters': characters(messages)})
        output = None
        if self.calls > 1:
            output = json.loads(messages[-1]['content'])['tool_result_untrusted']
            output = output.get('result', output)
            assert not output.get('error'), output.get('error')
        if self.calls == 1:
            action = self.tool('search_posts', {'limit': self.limit})
        elif self.calls == 2:
            self.first_page = output['items']
            assert self.first_page and output['coverage']['next_cursor']
            candidates = [s for item in self.first_page for s in item['snippets'] if s['field'] == 'body']
            assert candidates
            self.original_id, self.original_quote = candidates[0]['evidence_id'], candidates[0]['quote']
            action = self.tool('search_posts', {'limit': self.limit, 'cursor': output['coverage']['next_cursor']})
        elif self.calls == 3:
            self.second_page = output['items']
            action = self.tool('source_versions', {'post_ids': [self.first_page[0]['external_id']]})
        elif self.calls == 4:
            ids = self.ids(self.first_page)
            action = self.tool('read_evidence', {'evidence_ids': ids})
        elif self.calls == 5:
            if self.mixed:
                action = self.tool('search_comments', {'limit': self.limit})
            else:
                action = self.tool('read_evidence', {'evidence_ids': self.ids(self.second_page)})
        elif self.calls == 6:
            action = self.tool('read_evidence', {'evidence_ids': [self.original_id]})
        else:
            assert self.calls == 7
            assert output['items'][0]['evidence_id'] == self.original_id
            assert output['items'][0]['quote'] == self.original_quote
            self.reread_verified = True
            action = {'action': 'answer', 'outcome': 'answered', 'paragraphs': [
                {'text': '离线回放已按原证据标识重新读取当前有效的原文片段。', 'evidence_ids': [self.original_id]}],
                'limitations': ['这里只验证上下文大小与证据回读，不评价模型语义质量。']}
        return encode(action)

    def ids(self, items):
        candidates = [snippet['evidence_id'] for item in items for snippet in item['snippets'] if snippet['field'] == 'body']
        ids = list(dict.fromkeys([self.original_id] + candidates))[:10]
        assert ids
        return ids

    @staticmethod
    def tool(name, arguments):
        return {'action': 'tool', 'name': name, 'arguments': arguments}


async def case(directory, limit, mixed):
    store = KnowledgeStore(directory)
    imports = []
    for file in FILES:
        path = directory / file
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / file, path)
        source = store.register_source(path, platform='tieba', source_timezone='Asia/Shanghai')
        report = store.import_source(source['id'])
        assert report['status'] == 'completed', report
        imports.append({'file': file, 'records': report['valid']})
    model = ReplayModel(limit, mixed)
    harness = Harness(store, lambda: model)
    session = harness.create_session()['id']
    run_id = harness.start(session, '读取本地帖子资料，检查来源和评论，再回读早期原文依据。')['run_id']
    await harness.tasks[run_id]
    result = harness.run(run_id)
    assert result['status'] == 'completed', result['error']
    assert result['usage']['tool_calls'] == 6 and result['usage']['model_calls'] == 7
    assert model.reread_verified
    last = model.measurements[-1]
    append_total = sum(m['append_only_characters'] for m in model.measurements)
    current_total = sum(m['current_characters'] for m in model.measurements)
    with store.connection() as conn:
        references = [row[0] for row in conn.execute('SELECT result_refs FROM research_working_steps WHERE run_id=?', (run_id,))]
    assert model.original_quote not in '\n'.join(references)
    return {'case': ('mixed_posts_comments' if mixed else 'post_versions_reads') + f'_page_{limit}',
            'page_size': limit, 'imports': imports, 'trace': model.measurements,
            'final_append_only_characters': last['append_only_characters'],
            'final_current_characters': last['current_characters'],
            'final_reduction_percent': round(100 * (1 - last['current_characters'] / last['append_only_characters']), 2),
            'cumulative_append_only_characters': append_total, 'cumulative_current_characters': current_total,
            'cumulative_reduction_percent': round(100 * (1 - current_total / append_total), 2),
            'reread_exact_match': True, 'working_records_contain_no_quote_copy': True}


def main():
    fingerprints = {file: hashlib.sha256((ROOT / file).read_bytes()).hexdigest() for file in FILES}
    cases = []
    with tempfile.TemporaryDirectory(prefix='resume-context-', dir=ROOT / '.runtime') as temporary:
        for mixed in (False, True):
            for limit in (5, 10, 20):
                directory = Path(temporary) / f'{mixed}-{limit}'
                directory.mkdir()
                # Stable identities also stabilize ties in the production search order.
                identities = random.Random(20261010)
                with patch('uuid.uuid4', side_effect=lambda: uuid.UUID(int=identities.getrandbits(128), version=4)):
                    cases.append(asyncio.run(case(directory, limit, mixed)))
    assert fingerprints == {file: hashlib.sha256((ROOT / file).read_bytes()).hexdigest() for file in FILES}
    report = {'date': '2026-10-10', 'metric': 'message_content_unicode_characters_not_tokens',
              'baseline': 'counterfactual_append_only_same_initial_prompt_actions_tool_outputs_and_usage',
              'implementation': 'production_Harness_working_memory_rebuild',
              'method': 'six_paired_deterministic_replays_two_fixed_tool_workflows_three_page_sizes',
              'external_model_calls': 0, 'real_platform_requests': 0, 'source_sha256': fingerprints,
              'cases': cases,
              'summary': {'case_count': len(cases), 'model_calls_per_case': 7, 'tool_calls_per_case': 6,
                          'mean_final_reduction_percent': round(statistics.mean(c['final_reduction_percent'] for c in cases), 2),
                          'min_final_reduction_percent': min(c['final_reduction_percent'] for c in cases),
                          'max_final_reduction_percent': max(c['final_reduction_percent'] for c in cases),
                          'mean_cumulative_reduction_percent': round(statistics.mean(c['cumulative_reduction_percent'] for c in cases), 2),
                          'all_rereads_exact': all(c['reread_exact_match'] for c in cases), 'original_files_unchanged': True},
              'limits': ['A controlled offline replay, not actual LLM-generated investigations.',
                         'The append-only baseline is a counterfactual, not a measured historical release.',
                         'Characters are not tokens or measured API cost; no semantic quality gain is claimed.']}
    destination = ROOT / 'docs/benchmarks/resume-context-2026-10-10.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False))


if __name__ == '__main__':
    main()
