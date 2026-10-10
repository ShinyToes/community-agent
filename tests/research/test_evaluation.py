import pytest

from community_research.evaluation import evaluate_study


def test_labeled_sample_metrics_keep_unknown_separate():
    study = {'cases': [{'id': 'ambiguous_alias', 'gold': {
        'post_a': 'relevant', 'post_b': 'relevant', 'animal': 'drift',
        'short_reply': 'uncertain', 'other': 'irrelevant'},
        'methods': {'explicit_name': {'candidate_ids': ['post_a'], 'selected_ids': ['post_a'],
            'requests': 1, 'model_calls': 0, 'seconds': 1.2},
            'exploration': {'candidate_ids': ['post_a', 'post_b', 'post_b', 'animal', 'unlabeled'],
                'selected_ids': ['post_a', 'post_b', 'animal', 'unlabeled'],
                'requests': 3, 'model_calls': 2, 'seconds': 5.0}}}]}
    result = evaluate_study(study)
    explicit = result['cases'][0]['methods']['explicit_name']
    expanded = result['cases'][0]['methods']['exploration']
    assert explicit['known_sample_recall'] == 0.5
    assert expanded['known_sample_recall'] == 1.0
    assert expanded['judged_precision'] == 0.6667
    assert expanded['selected_drift'] == 1
    assert expanded['unlabeled_selected'] == 1
    assert expanded['duplicate_candidates'] == 1
    assert result['scope'] == 'labeled_sample_only'


def test_selected_must_have_been_discovered():
    with pytest.raises(ValueError, match='selected_not_discovered'):
        evaluate_study({'cases': [{'id': 'x', 'gold': {'a': 'relevant'}, 'methods': {
            'baseline': {'candidate_ids': [], 'selected_ids': ['a'], 'requests': 0,
                         'model_calls': 0, 'seconds': 0}}}]})
