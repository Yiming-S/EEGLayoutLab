"""The project request checks of ``schemas.projects`` are Node's (phase 2 slice 9), messages and statuses included.

The variants are those of the schema parity corpus (``tests/schema_parity/formats/project-*.mjs``), which runs
Node's own ``ProjectService.body``, ``attachment`` and ``ProjectStore`` checks (``project-validation.mjs``) and
records Node's message for every refused body. ``tests/test_schema_parity.py`` and ``tests/test_schema_service.py``
already compare acceptance and the canonical bytes through the registry; here the normalizers themselves: Node's
message, the status Node gives it (409 for the electrode names, else 400), every message reached, the input left
unchanged, and Python values (``int``, tuples, ``bool``, ``UNDEFINED`` members) treated as Node treats their
JavaScript counterparts.
"""
from __future__ import annotations

import copy

import pytest

from schema_parity_support import FORMATS, body_text, needs_node, require

require('pydantic')

from eeglayoutlab.schemas import jsjson, projects  # noqa: E402
from eeglayoutlab.schemas.projects import (  # noqa: E402
    ELECTRODE_NAMES, INVALID_ANNOTATION, INVALID_ATTACHMENT, INVALID_FIELDS, INVALID_JSON, NO_ENTRY_CHANGES,
    NO_PROJECT_CHANGES, RECEIPT_REQUIRED, RECORD_REQUIRED, REVISION, UNDEFINED, ProjectRequestError,
)
from eeglayoutlab.schemas.registry import REQUEST_FORMATS  # noqa: E402

NORMALIZE = {'project-create': projects.normalize_create, 'project-entry': projects.normalize_entry,
             'project-entry-delete': projects.normalize_entry_delete,
             'project-entry-patch': projects.normalize_entry_patch, 'project-patch': projects.normalize_patch}
# Every message Node's checks give before the project is read, by format.
MESSAGES = {
    'project-create': {INVALID_JSON, INVALID_FIELDS, 'Invalid project title.', 'Invalid researcher name.',
                       'Invalid project notes.'},
    'project-entry': {INVALID_JSON, INVALID_ATTACHMENT, INVALID_ANNOTATION, RECEIPT_REQUIRED, RECORD_REQUIRED,
                      ELECTRODE_NAMES, 'Invalid entry title.', 'Invalid entry notes.', REVISION},
    'project-entry-delete': {INVALID_JSON, REVISION},
    'project-entry-patch': {INVALID_JSON, INVALID_FIELDS, NO_ENTRY_CHANGES, 'Invalid title.', 'Invalid notes.',
                            REVISION},
    'project-patch': {INVALID_JSON, INVALID_FIELDS, NO_PROJECT_CHANGES, 'Invalid title.', 'Invalid owner_name.',
                      'Invalid notes.', REVISION},
}
VARIANTS = [(name, variant) for name in NORMALIZE for variant in FORMATS.get(name, []) if variant['parsed']]


def _outcome(normalize, value):
    try:
        return jsjson.stringify(normalize(value)), None
    except ProjectRequestError as error:
        assert error.project_safe is True and error.message == str(error)
        assert error.status == (409 if error.message == ELECTRODE_NAMES else 400), error.message
        return None, error.message


@needs_node
@pytest.mark.parametrize('case', VARIANTS, ids=lambda case: f"{case[0]}/{case[1]['name']}")
def test_the_normalizers_give_node_value_or_node_message(case):
    name, variant = case
    value = jsjson.parse(body_text(variant))
    before = copy.deepcopy(value)
    assert _outcome(NORMALIZE[name], value) == (variant['canonical'], variant.get('error'))
    assert value == before


@needs_node
@pytest.mark.parametrize('name', sorted(NORMALIZE))
def test_the_variants_reach_every_node_message(name):
    variants = FORMATS.get(name, [])
    assert variants, name
    assert {variant['error'] for variant in variants if variant.get('error')} == MESSAGES[name]
    assert any(variant['accepted'] for variant in variants)


def test_the_registry_holds_the_project_formats():
    for name, normalize in NORMALIZE.items():
        assert REQUEST_FORMATS[name].canonical is projects.canonical
    assert REQUEST_FORMATS['project-entry'].options == {'entry_kinds': ('layout', 'editor', 'source')}
    accepted = {'title': ' Study ', 'owner_name': 'R'}
    assert REQUEST_FORMATS['project-create'].normalize(accepted) == projects.normalize_create(accepted)
    with pytest.raises(ValueError):
        REQUEST_FORMATS['project-create'].normalize({'title': ''})


def test_python_values_are_read_as_their_javascript_counterparts():
    workflow = {'reference_entry_id': None, 'candidate_entry_id': None, 'comparison_href': None}
    patch = {'revision': 3, 'notes': ' n ', 'workflow': workflow}
    out = projects.normalize_patch(patch)
    assert out == {'revision': 3, 'notes': 'n', 'workflow': workflow} and out['workflow'] is not workflow
    assert jsjson.stringify(out) == jsjson.stringify(projects.normalize_patch(jsjson.parse(jsjson.stringify(patch))))
    assert projects.normalize_patch({'revision': 1.0, 'title': 'T', 'workflow': ('a',)})['workflow'] == ['a']
    for revision in (True, False, 0, -1, 1.5, 2 ** 53, '1', None, [1], {}, float('nan'), float('inf')):
        with pytest.raises(ProjectRequestError, match='^A current project revision is required.$'):
            projects.normalize_entry_delete({'revision': revision})
    assert projects.normalize_entry_delete({'revision': 2 ** 53 - 1, 'other': 1}) == {'revision': 2 ** 53 - 1}
    for body in ((), [], ('title',), 'x', None, 1):
        with pytest.raises(ProjectRequestError, match='^Invalid project JSON.$'):
            projects.normalize_create(body)
    # An undefined member is skipped where Node tests `!== undefined` and defaulted where it writes `??`.
    assert projects.normalize_patch({'revision': 1, 'title': UNDEFINED, 'notes': 'x'}) == {'revision': 1, 'notes': 'x'}
    assert projects.normalize_create({'title': 'T', 'owner_name': 'R', 'notes': UNDEFINED})['notes'] == ''
    assert projects.normalize_entry({'revision': 1, 'kind': 'layout', 'record_id': 'a' * 64, 'title': UNDEFINED,
                                     'annotation_id': UNDEFINED, 'receipt_id': UNDEFINED}) == {
        'revision': 1, 'kind': 'layout', 'record_id': 'a' * 64}
    with pytest.raises(ProjectRequestError) as caught:
        projects.normalize_entry({'revision': 1, 'kind': 'layout', 'record_id': 'a' * 64, 'annotation_id': ['b' * 64]})
    assert (caught.value.status, caught.value.message) == (409, ELECTRODE_NAMES)
    # Texts count UTF-16 units and trim JavaScript white space only.
    assert projects.normalize_create({'title': '﻿' + 'x' * 197 + '😀', 'owner_name': '　R\u0085'}) == {
        'title': 'x' * 197 + '😀', 'owner_name': 'R\u0085', 'notes': ''}
    with pytest.raises(ProjectRequestError, match='^Invalid project title.$'):
        projects.normalize_create({'title': 'x' * 199 + '😀', 'owner_name': 'R'})


def test_the_workflow_reads_undefined_members_as_node_does():
    entries = [{'id': '0a0a0000-0000-4000-8000-000000000001', 'kind': 'layout', 'record_id': '1' * 64,
                'summary': {'protocol': 'cache'}}]
    assert projects.workflow({'reference_entry_id': UNDEFINED, 'candidate_entry_id': entries[0]['id'],
                              'comparison_href': UNDEFINED}, entries) == {
        'reference_entry_id': None, 'candidate_entry_id': entries[0]['id'], 'comparison_href': None}
    for href in ('', None, UNDEFINED):
        assert projects.workflow({'comparison_href': href}, entries)['comparison_href'] is None
    for href in (0, False, [], {}):
        with pytest.raises(ProjectRequestError, match='^Invalid project comparison link.$'):
            projects.workflow({'comparison_href': href}, entries)
