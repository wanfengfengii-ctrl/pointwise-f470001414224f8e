from collections import deque


def validate_acyclic(nodes, transfers):
    successors = {node: [] for node in nodes}
    indegree = dict.fromkeys(successors, 0)
    for transfer in transfers:
        if transfer.start not in successors or transfer.end not in indegree:
            raise ValueError('ENDPOINT_NOT_IN_DRAFT')
        successors[transfer.start].append(transfer.end)
        indegree[transfer.end] += 1
    ready = deque(node for node, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        node = ready.popleft()
        visited += 1
        for child in successors[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(indegree):
        raise ValueError('CYCLIC_DAY')
