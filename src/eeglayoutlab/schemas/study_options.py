"""Robustness-study option lists (webapp/contracts/robustness-study.ts and webapp/server/studies/protocol.mjs).

Plain tuples without Pydantic, shared by ``jobs.studies`` and the registry, so the registry, which the application
loads when it is built, imports no job module.
"""
from __future__ import annotations

STUDY_PROTOCOLS = ('noise_seeds', 'grid_displacements', 'heads')
# webapp/contracts/robustness-study.ts (StudyStatus, StudyCaseStatus) and the lists of studies/store.mjs.
STUDY_STATUSES = ('draft', 'running', 'paused_recovery', 'paused_resource', 'cancelling', 'completed',
                  'completed_with_failures', 'cancelled')
CASE_STATUSES = ('pending', 'submitting', 'queued', 'running', 'cancelling', 'completed', 'failed', 'cancelled',
                 'failed_uncertain')
NOMINAL_METRICS = ('field_relative', 'field_absolute', 'reference_field_absolute', 'sensitivity_tail',
                   'localization_relative', 'median_mm', 'p90_mm', 'reference_median_mm', 'reference_p90_mm')
TRIAL_METRICS = ('field_relative', 'fixed_estimator_field_relative', 'sensitivity_tail')
