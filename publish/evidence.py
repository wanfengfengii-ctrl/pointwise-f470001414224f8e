from dataclasses import dataclass


Relation = tuple[str, str]
JointRelation = tuple[Relation, Relation]


def _pair_key(first, second):
    return (first, second) if first <= second else (second, first)


@dataclass(frozen=True)
class EligibilityEvidence:
    singles: frozenset[Relation]
    pairs: frozenset[JointRelation]

    def allows_single(self, start, end):
        return (start, end) in self.singles

    def allows_pair(self, first, second):
        return _pair_key(first, second) in self.pairs


def _relation(entry, public_ids):
    if not isinstance(entry, list) or len(entry) != 2:
        raise ValueError('INVALID_EVIDENCE')
    start, end = entry
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError('INVALID_EVIDENCE')
    if start == end or start not in public_ids or end not in public_ids:
        raise ValueError('INVALID_EVIDENCE')
    return start, end


def validate_evidence(value, public_ids):
    if not isinstance(value, dict) or set(value) != {'singles', 'pairs'}:
        raise ValueError('INVALID_EVIDENCE')
    if not isinstance(value['singles'], list) or not isinstance(value['pairs'], list):
        raise ValueError('INVALID_EVIDENCE')
    singles = frozenset(_relation(entry, public_ids) for entry in value['singles'])
    pairs = set()
    for entry in value['pairs']:
        if not isinstance(entry, list) or len(entry) != 2:
            raise ValueError('INVALID_EVIDENCE')
        first = _relation(entry[0], public_ids)
        second = _relation(entry[1], public_ids)
        if first not in singles or second not in singles:
            raise ValueError('INVALID_EVIDENCE')
        pairs.add(_pair_key(first, second))
    return EligibilityEvidence(singles, frozenset(pairs))
