import json
from dataclasses import asdict

from .archive import fetch


def export_excerpt(db, result_id):
    result = fetch(db, result_id)
    return json.dumps({
        'result_id': result.result_id,
        'parents': [asdict(parent) for parent in result.parents],
        'samples': [
            {**asdict(sample), 'interface': interface}
            for sample, interface in zip(result.samples, result.interfaces)
        ],
        'receipt': asdict(result.receipt),
    }, sort_keys=True, separators=(',', ':'))
