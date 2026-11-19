from itertools import combinations_with_replacement

from .evidence import EligibilityEvidence
from .routes import collect_route_witnesses


def build_eligibility(frozen):
    witnesses = collect_route_witnesses(frozen)
    singles = frozenset(witnesses)
    pairs = set()
    for first, second in combinations_with_replacement(sorted(singles), 2):
        if any(
            left.isdisjoint(right)
            for left in witnesses[first]
            for right in witnesses[second]
        ):
            pairs.add((first, second))
    return EligibilityEvidence(singles, frozenset(pairs))
