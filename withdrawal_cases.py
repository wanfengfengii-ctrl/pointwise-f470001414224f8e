"""Small source fixtures and a V1 reference comparison for withdrawal review."""

import json
from contextlib import closing

from freeze import close_day, open_successor
from intake import add_node, create_draft, open_source, record, withdraw_record
from publish import publish_pack
from results import issue, open_night
from review import ReviewRequest, import_pack
from samples import BATCH, FRONT, FRONT_BOUNDARIES, REAR, REAR_BOUNDARIES, SAMPLES, stage_front, stage_rear


def stage_withdrawal_front(db, *, spare, withdrawn=(), revision="R1"):
    draft = create_draft(db, FRONT, BATCH, f"draft-{revision}")
    for node in ("a1", "a2", "p", "q", "hidden-in", "hidden-out"):
        add_node(db, draft.key, node)
    spare_endpoints = ("a1", "p") if spare else ("hidden-in", "hidden-out")
    for name, start, end in (
        ("private-r", "a1", "p"),
        ("private-s", "a1", "p"),
        ("private-t", *spare_endpoints),
        ("private-alternate", "a1", "q"),
        ("private-other-sample", "a2", "q"),
    ):
        if name not in withdrawn:
            record(db, draft.key, name, start, end)
    return publish_pack(db, close_day(db, draft.key, revision, FRONT_BOUNDARIES).key)


def stage_fallback_rear(db):
    draft = create_draft(db, REAR, BATCH, "D1")
    for node in ("p", "q", "b1", "b2"):
        add_node(db, draft.key, node)
    for name, start, end in (
        ("private-lab-p", "p", "b1"),
        ("private-lab-q-first", "q", "b1"),
        ("private-lab-q-second", "q", "b2"),
    ):
        record(db, draft.key, name, start, end)
    return publish_pack(db, close_day(db, draft.key, "R1", REAR_BOUNDARIES).key)


def front_comparison(spare, withdrawn=()):
    with closing(open_source(":memory:")) as db:
        return stage_withdrawal_front(db, spare=spare, withdrawn=withdrawn)


def v1_binding(front, rear, samples=SAMPLES):
    with closing(open_night(":memory:")) as night:
        front_id = import_pack(night, front)
        rear_id = import_pack(night, rear)
        return issue(night, ReviewRequest(front_id, rear_id, samples)).interfaces


def check_reference():
    with closing(open_source(":memory:")) as db:
        rear = stage_fallback_rear(db)
    base = front_comparison(False)
    assert base == front_comparison(True)
    observations = []
    for spare in (False, True):
        for removed in ((), ("private-r",), ("private-s",), ("private-r", "private-s")):
            binding = v1_binding(front_comparison(spare, removed), rear)
            expected = ("q", "q") if len(removed) == 2 and not spare else ("p", "q")
            assert binding == expected, (spare, removed, binding)
            observations.append({"spare_to_p": spare, "removed": removed, "v1_binding": binding})

    with closing(open_source(":memory:")) as db:
        front_parallel = stage_front(db, "D1", "R1", parallel=True)
        next_draft = open_successor(db, (FRONT, BATCH, "R1"), "D2")
        withdraw_record(db, next_draft.key, "r1")
        reduced_front = publish_pack(db, close_day(db, next_draft.key, "R2", FRONT_BOUNDARIES).key)
    with closing(open_source(":memory:")) as db:
        rear_parallel = stage_rear(db)
    assert v1_binding(front_parallel, rear_parallel) == ("p", "q")
    single_bindings = [v1_binding(reduced_front, rear_parallel, (sample,)) for sample in SAMPLES]
    assert single_bindings == [("p",), ("q",)]
    try:
        v1_binding(reduced_front, rear_parallel)
    except ValueError as exc:
        if str(exc) != "NO_COMMON_EVIDENCE":
            raise
    else:
        raise AssertionError("shared remaining record should block joint signing")
    return {
        "same_v1_parent": True,
        "fresh_v1_signatures": observations,
        "shared_record": {"single_bindings": single_bindings, "joint": "NO_COMMON_EVIDENCE"},
    }


if __name__ == "__main__":
    print(json.dumps(check_reference(), indent=2))
