"""Read-only exact coordinate qualification before batch cache warming."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import json
import subprocess
import hashlib
import numpy as np
from scipy.spatial import cKDTree

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
from compact_eeg.workflows.reception_forward_provider import _load_bundle,_validate_record,_exact_rows
node="""import fs from 'node:fs';import {areaRecords} from './webapp/server/local-data-library.mjs';const p=JSON.parse(fs.readFileSync('results/v2/current_strict_area_budget_study.json'));console.log(JSON.stringify(areaRecords(JSON.parse(fs.readFileSync(p.report)),{file:p.report,sha256:p.sha256})));"""
records=json.loads(subprocess.check_output(['node','--input-type=module','-e',node],cwd=root))
pointer=json.loads((root/'results/v2/current_strict_area_budget_study.json').read_text())
if hashlib.sha256((root/pointer['report']).read_bytes()).hexdigest()!=pointer['sha256']:raise ValueError('Report checksum mismatch')
bundle=_load_bundle(root)
tree=cKDTree(bundle['bank_xyz']);eligible=[];excluded=[]
for record in records:
 xyz,_=_validate_record(root,record,bundle)
 indices=_exact_rows(xyz,bundle['bank_xyz'])
 if indices is not None:eligible.append(record['id'])
 else:
  # Distances diagnose the rejection only; they are never used to select H rows.
  distances,_=tree.query(xyz)
  excluded.append({'id':record['id'],'label':record['label'],'reason':'not_bitwise_identical_to_bank','max_difference_mm':float(distances.max()),'mismatched_points':int(np.count_nonzero(distances))})
output={'version':1,'report_path':pointer['report'],'report_sha256':pointer['sha256'],
 'bank_path':bundle['provenance']['bank_path'],'bank_sha256':bundle['provenance']['bank_sha256'],
 'eligible':eligible,'excluded':excluded,'no_neighbour_substitution':True}
directory=root/'results/precompute';directory.mkdir(parents=True,exist_ok=True)
(directory/'source-preflight.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
print(json.dumps({'eligible_layouts':len(eligible),'excluded':excluded,'planned_requests':len(eligible)*69*2},ensure_ascii=False))
