"""Shared wire samples checked at the actual Python validation boundary; no solver/data."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from compact_eeg.local_radius_compute import validate_request as validate_radius
from compact_eeg.workflows.design_evaluation import validate_request as validate_design
from compact_eeg.workflows.source_reception import validate_request as validate_source
from compact_eeg.workflows.source_reception_v2 import validate_request as validate_source_v2


ROOT = Path(__file__).resolve().parents[1]
CORPUS = json.loads((ROOT / 'contracts/fixtures/requests.json').read_text())


def validate(service, request):
    if service == 'source':
        return (validate_source_v2 if 'mode' in request else validate_source)(request)
    return {'radius': validate_radius, 'design': validate_design}[service](request)


@pytest.mark.parametrize('sample', CORPUS['cases'], ids=lambda sample: sample['name'])
def test_shared_request_corpus(sample):
    assert CORPUS['version'] == 'eeglayoutlab-request-fixtures/1'
    # HTTP normalization precedes the worker. The corpus records that exact wire
    # request, including defaults/field filtering, separately from worker output.
    request = deepcopy(sample['canonical'] if sample['valid'] else sample['request'])
    original = deepcopy(request)
    if sample['valid']:
        assert validate(sample['service'], request) == sample['worker']
    else:
        with pytest.raises(ValueError):
            validate(sample['service'], request)
    assert request == original
