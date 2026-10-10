"""Score retrieval runs against a separately labeled, finite sample.

The sample is explicit: these numbers are never estimates of platform-wide recall.
"""

from collections import Counter


LABELS = {'relevant', 'irrelevant', 'uncertain', 'drift'}


def evaluate_case(case):
    gold = case['gold']
    if not isinstance(gold, dict) or not gold or any(label not in LABELS for label in gold.values()):
        raise ValueError('invalid_gold')
    known_relevant = {ident for ident, label in gold.items() if label == 'relevant'}
    if not isinstance(case.get('methods'), dict) or not case['methods']:
        raise ValueError('invalid_methods')
    methods = {}
    for name, run in case['methods'].items():
        candidates, selected = run.get('candidate_ids'), run.get('selected_ids')
        if not name or not isinstance(candidates, list) or not isinstance(selected, list) or any(
            not isinstance(ident, str) or not ident for ident in candidates + selected
        ):
            raise ValueError('invalid_run')
        if not set(selected).issubset(candidates):
            raise ValueError('selected_not_discovered')
        for key in ('requests', 'model_calls'):
            if type(run.get(key)) is not int or run[key] < 0:
                raise ValueError('invalid_cost')
        if type(run.get('seconds')) not in (int, float) or run['seconds'] < 0:
            raise ValueError('invalid_cost')
        unique_candidates, unique_selected = set(candidates), set(selected)
        judged_selected = {ident for ident in unique_selected if gold.get(ident) in ('relevant', 'irrelevant', 'drift')}
        methods[name] = {
            'known_relevant_found': len(unique_candidates & known_relevant),
            'known_relevant_total': len(known_relevant),
            'known_sample_recall': round(len(unique_candidates & known_relevant) / len(known_relevant), 4) if known_relevant else None,
            'selected_relevant': len(unique_selected & known_relevant),
            'judged_selected': len(judged_selected),
            'judged_precision': round(len(unique_selected & known_relevant) / len(judged_selected), 4) if judged_selected else None,
            'selected_drift': sum(gold.get(ident) == 'drift' for ident in unique_selected),
            'uncertain_selected': sum(gold.get(ident) == 'uncertain' for ident in unique_selected),
            'unlabeled_selected': sum(ident not in gold for ident in unique_selected),
            'duplicate_candidates': len(candidates) - len(unique_candidates),
            'requests': run['requests'], 'model_calls': run['model_calls'], 'seconds': run['seconds'],
        }
    return {'case_id': case['id'], 'gold_counts': dict(Counter(gold.values())), 'methods': methods,
            'scope': 'labeled_sample_only'}


def evaluate_study(study):
    if not isinstance(study, dict) or not isinstance(study.get('cases'), list) or not study['cases']:
        raise ValueError('invalid_study')
    ids = [case.get('id') for case in study['cases']]
    if any(not isinstance(ident, str) or not ident for ident in ids) or len(ids) != len(set(ids)):
        raise ValueError('invalid_case_ids')
    return {'scope': 'labeled_sample_only', 'cases': [evaluate_case(case) for case in study['cases']]}
