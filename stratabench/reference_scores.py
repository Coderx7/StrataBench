"""Curated precision-labelled references. Unavailable is never replaced with an invented score."""
import copy

from .common import ROOT, read_json


def catalog():
    return read_json(ROOT / 'datasets/reference-scores.json')


def reference_rows(groups):
    source = catalog()
    by_group = {score['group']: score for score in source['scores']}
    result = []
    for group in sorted(set(groups)):
        if group in by_group:
            row = copy.deepcopy(by_group[group])
            row['available'] = True
        else:
            row = {'group': group, 'available': False, 'score_percent': None, 'weight_precision': None,
                   'directly_comparable': False,
                   'reason': source['unavailable'].get(group, 'Custom/generated tasks have no published original-model reference.')}
        result.append(row)
    return result
