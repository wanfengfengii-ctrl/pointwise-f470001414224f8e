from review.decisions import decide

from .archive import IssuedResult, write_result
from .receipts import write_receipt
from .store import issue_transaction


def issue(db, request):
    decision = decide(db, request)
    with issue_transaction(db):
        result_id = write_result(db, decision)
        receipt = write_receipt(db, result_id)
    return IssuedResult(
        result_id, decision.parents, decision.request.samples, decision.interfaces, receipt,
    )
