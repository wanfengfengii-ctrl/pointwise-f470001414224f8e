from itertools import product


def _allows(evidence, relations):
    if len(relations) == 1:
        return evidence.allows_single(*relations[0])
    return evidence.allows_pair(*relations)


def find_binding(front, rear, request, seam):
    # The sorted seam gives product order over whole request-ordered tuples.
    for binding in product(seam.interfaces, repeat=len(request.samples)):
        upstream = tuple((sample.start, port) for sample, port in zip(request.samples, binding))
        downstream = tuple((port, sample.end) for sample, port in zip(request.samples, binding))
        if _allows(front.evidence, upstream) and _allows(rear.evidence, downstream):
            return binding
    return None
