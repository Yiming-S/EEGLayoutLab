"""Request schemas: the planned single definition of wire formats (design 0001, decision 4).

Phase 0 spike: only the design-evaluation request is ported.
"""
from .design_evaluation import DesignEvaluationRequest, ElectrodeDesign, canonical_json, normalize_design_request

__all__ = ['DesignEvaluationRequest', 'ElectrodeDesign', 'canonical_json', 'normalize_design_request']
