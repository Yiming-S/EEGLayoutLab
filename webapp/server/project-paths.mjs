/** Local checkout layout. No data relocation or cwd-dependent path inference. */
import { resolve, join } from 'node:path';

export const NATIVE_RUNTIME_RELATIVE = '.runtime/simnibs-4.6.0';
export const repositoryRootForWebapp = (webappRoot) =>
  resolve(webappRoot, '..');
export const nativePythonPath = (root) =>
  join(root, NATIVE_RUNTIME_RELATIVE, 'bin/python');

// Actual implementations must be fingerprinted, not just legacy CLI shims.
const prefix = 'src/compact_eeg/workflows/';
export const WORKFLOW_BASE = [prefix + '__init__.py', prefix + 'paths.py'];
export const DESIGN_WORKFLOW = [
  ...WORKFLOW_BASE,
  prefix + 'design_evaluation.py',
  prefix + 'head_model.py',
  prefix + 'reception_forward_provider.py',
  prefix + 'shared_native_forward.py',
  prefix + 'scalp_node_table.py',
  prefix + 'head_package.py',
];
export const RECEPTION_WORKFLOW = [
  prefix + '__init__.py',
  prefix + 'source_reception.py',
];
export const RECEPTION_V2_WORKFLOW = [
  ...WORKFLOW_BASE,
  prefix + 'source_reception.py',
  prefix + 'source_reception_v2.py',
  prefix + 'reception_forward_provider.py',
  prefix + 'shared_native_forward.py',
];
export const EDITOR_WORKFLOW = [prefix + 'electrode_editor.py'];
