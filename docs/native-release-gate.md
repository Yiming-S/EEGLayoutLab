# Native calculation release check

`verify_native_release.py` checks a new native FEM solve against a previously qualified reference. It uses a separate workspace, copies the declared source and frozen inputs, and excludes historical forward and signal caches. The application’s scientific requests, thread settings and calculation code retain their existing definitions.

Use the scientific Python environment qualified for the reference. The reference manifest and its files must already exist. They contain full numerical results and are kept outside source control.

```bash
python scripts/verify_native_release.py \
  --source-root /absolute/path/EEGLayoutLab \
  --reference-manifest /absolute/path/reference/reference.json \
  --workspace /absolute/path/EEGLayoutLab/artifacts/native-release-check \
  --python /absolute/path/qualified-python
```

This command prints the plan. Add `--execute-new-fem` to create the new workspace and run the calculation. Choose a new workspace path for each check; the tool does not replace existing evidence.

The reference schema is `eeglayoutlab-native-release-reference/1`. It records the scientific file identities and SHA-256 values of nine artifacts: the coordinate design request, evaluation result and full forward matrix, followed by the request payload, result and full forward matrix for each of the single-source and multi-source experiments. Reference paths are relative to the manifest directory. The manifest binds these inputs and results to their original scientific identities.

The check records whether a native model was actually constructed and solved. It compares the complete forward matrices, evaluated coordinates, non-timing quality fields, signal arrays and scientific result fields. A cache read alone cannot pass as a new FEM solve. Summary and failure evidence remain under the new workspace’s `native-release-report/` directory.

The exact comparison qualifies numerical regression in the reference environment. A different operating system, processor architecture or numerical environment requires its own qualification. Independent-head and mesh-convergence studies are separate scientific work.
