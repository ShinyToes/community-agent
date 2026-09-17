"""Score parsing and weighted totals, independent of SQL or HTTP."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def parse_score(value):
    if value is None or str(value).strip() == '':
        return None
    try:
        result = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError('成绩必须是 0–100 之间的数字') from None
    if not result.is_finite() or not Decimal(0) <= result <= Decimal(100):
        raise ValueError('成绩必须是 0–100 之间的有限数字')
    return result


def validate_weights(values):
    try:
        weights = tuple(Decimal(str(v)) for v in values)
    except InvalidOperation:
        raise ValueError('成绩权重必须为数字') from None
    if any(not w.is_finite() or not 0 <= w <= 1 for w in weights) or sum(weights) != 1:
        raise ValueError('成绩权重必须在 0–1 之间，且总和为 1')
    return weights


def weighted_total(scores, weights):
    weights = validate_weights(weights)
    scores = tuple(parse_score(s) for s in scores)
    # Do not publish a final grade before all required components are available.
    if any(s is None and w > 0 for s, w in zip(scores, weights)):
        return None
    return sum((s or Decimal(0)) * w for s, w in zip(scores, weights)).quantize(
        Decimal('0.1'), rounding=ROUND_HALF_UP)
