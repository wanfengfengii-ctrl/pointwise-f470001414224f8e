from collections import defaultdict


def collect_route_witnesses(frozen):
    outgoing = defaultdict(list)
    for transfer in frozen.transfers:
        outgoing[transfer.start].append(transfer)

    public_at_node = defaultdict(list)
    for point in frozen.boundaries:
        public_at_node[point.node].append(point.public_id)

    witnesses = defaultdict(list)
    for origin in frozen.boundaries:
        # A frozen graph is acyclic. Each nonempty walk is a directed chain.
        pending = [(origin.node, frozenset())]
        while pending:
            node, records = pending.pop()
            if records:
                for target in public_at_node.get(node, ()):
                    witnesses[origin.public_id, target].append(records)
            for transfer in reversed(outgoing.get(node, ())):
                pending.append((transfer.end, records | {transfer.record_id}))
    return dict(witnesses)
