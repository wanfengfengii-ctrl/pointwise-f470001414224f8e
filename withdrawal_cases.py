"""Small source fixtures and a V1 reference comparison for withdrawal review."""

import json
from contextlib import closing

from freeze import close_day, open_successor
from freeze.history import FrozenRevision, read_revision
from intake import add_node, create_draft, open_source, record, withdraw_record
from publish import publish_pack, withdrawal_notice, withdrawal_sheet
from publish.eligibility import build_eligibility
from results import issue, open_night, review_withdrawals
from review import ReviewRequest, import_pack, import_withdrawal_notice, import_withdrawal_sheet
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


def withdrawn_front_evidence(frozen, removed):
    kept = tuple(item for item in frozen.transfers if item.record_id not in removed)
    return build_eligibility(FrozenRevision(
        frozen.station, frozen.batch, frozen.revision, frozen.draft,
        frozen.base_revision, frozen.nodes, kept, frozen.boundaries,
    ))


def check_withdrawal_wire():
    """Compare the implemented withdrawal review with a V1 reduced-record recut."""
    observations = []
    for spare in (False, True):
        for removed in ((), ("private-r",), ("private-s",), ("private-r", "private-s")):
            with closing(open_source(":memory:")) as prep, closing(open_source(":memory:")) as lab:
                front_pack = stage_withdrawal_front(prep, spare=spare)
                rear_pack = stage_fallback_rear(lab)
                front_sheet = withdrawal_sheet(prep, (FRONT, BATCH, "R1"))
                rear_sheet = withdrawal_sheet(lab, (REAR, BATCH, "R1"))
                notices = [
                    withdrawal_notice(prep, (FRONT, BATCH, "R1"), f"notice-{index}", [name])
                    for index, name in enumerate(removed)
                ]
                frozen = read_revision(prep, (FRONT, BATCH, "R1"))
                rear_frozen = read_revision(lab, (REAR, BATCH, "R1"))
            reference_front = withdrawn_front_evidence(frozen, set(removed))
            reference_rear = build_eligibility(rear_frozen)
            upstream = tuple((sample.start, port) for sample, port in zip(SAMPLES, ("p", "q")))
            downstream = tuple((port, sample.end) for sample, port in zip(SAMPLES, ("p", "q")))
            if not removed:
                expected = "NO_WITHDRAWAL_NOTICE"
            elif reference_front.allows_pair(*upstream) and reference_rear.allows_pair(*downstream):
                expected = "valid"
            else:
                expected = "invalid"
            with closing(open_night(":memory:")) as night:
                front_id = import_pack(night, front_pack)
                rear_id = import_pack(night, rear_pack)
                result = issue(night, ReviewRequest(front_id, rear_id, SAMPLES))
                import_withdrawal_sheet(night, front_sheet)
                import_withdrawal_sheet(night, rear_sheet)
                for notice in reversed(notices):
                    import_withdrawal_notice(night, notice)
                if removed:
                    review = review_withdrawals(night, result.result_id)
                else:
                    try:
                        review_withdrawals(night, result.result_id)
                    except LookupError as exc:
                        review = {"status": str(exc), "interfaces": list(result.interfaces)}
                    else:
                        raise AssertionError("review without notice should be refused")
            assert review["status"] == expected, (spare, removed, review["status"], expected)
            observations.append({
                "spare_to_p": spare, "removed": list(removed),
                "interfaces": review["interfaces"], "status": review["status"],
            })

    with closing(open_source(":memory:")) as prep, closing(open_source(":memory:")) as lab:
        front_pack = stage_front(prep, "D1", "R1", parallel=True)
        rear_pack = stage_rear(lab)
        front_sheet = withdrawal_sheet(prep, (FRONT, BATCH, "R1"))
        rear_sheet = withdrawal_sheet(lab, (REAR, BATCH, "R1"))
        notice = withdrawal_notice(prep, (FRONT, BATCH, "R1"), "drop-r1", ["r1"])
        frozen = read_revision(prep, (FRONT, BATCH, "R1"))
    reference = withdrawn_front_evidence(frozen, {"r1"})
    with closing(open_night(":memory:")) as night:
        front_id = import_pack(night, front_pack)
        rear_id = import_pack(night, rear_pack)
        result = issue(night, ReviewRequest(front_id, rear_id, SAMPLES))
        import_withdrawal_sheet(night, front_sheet)
        import_withdrawal_sheet(night, rear_sheet)
        import_withdrawal_notice(night, notice)
        joint = review_withdrawals(night, result.result_id)
        singles = []
        for sample in SAMPLES:
            each = review_withdrawals(night, issue(
                night, ReviewRequest(front_id, rear_id, (sample,)),
            ).result_id)
            singles.append(each["status"])
    assert joint["status"] == "invalid", joint
    assert singles == ["valid", "valid"], singles
    assert reference.allows_pair(*[(s.start, s.end) for s in SAMPLES]) is False
    return {"fresh_withdrawal_reviews": observations,
            "shared_remaining": {"joint": joint["status"], "singles": singles}}


if __name__ == "__main__":
    report = check_reference()
    report["withdrawal_wire"] = check_withdrawal_wire()
    print(json.dumps(report, indent=2))
