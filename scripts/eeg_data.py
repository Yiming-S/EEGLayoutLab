#!/usr/bin/env python3
"""Worker for recorded EEG: covariance summaries and data-prior fits.

Request on stdin, JSON events on stdout (``progress``, then ``result`` or ``error``):
  {"action": "summary", "path": FILE, "band_hz": [1, 40], "epoch_s": 2, "label": TEXT|null}
  {"action": "prior", "files": [SUMMARY.json, ...]}
Implementation: compact_eeg.workflows.eeg_recording and compact_eeg.workflows.data_prior.
"""
from pathlib import Path
import json
import os
import sys

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ.setdefault(key, '1')
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    def emit(event):
        print(json.dumps(event, ensure_ascii=False, allow_nan=False), flush=True)

    def progress(value, message):
        emit({'type': 'progress', 'progress': value, 'message': message})
    try:
        body = sys.stdin.read((1 << 20) + 1)
        if len(body) > 1 << 20:
            raise ValueError('Request too large')
        request = json.loads(body)
        if not isinstance(request, dict):
            raise ValueError('Request must be an object')
        if request.get('action') == 'summary':
            from compact_eeg.workflows import eeg_recording
            if set(request) - {'action', 'path', 'band_hz', 'epoch_s', 'label'}:
                raise ValueError('Unsupported summary fields')
            if not isinstance(request.get('path'), str) or not request['path']:
                raise ValueError('summary needs the recording path')
            band = request.get('band_hz', list(eeg_recording.DEFAULT_BAND_HZ))
            if not isinstance(band, list) or len(band) != 2 or not all(isinstance(b, (int, float)) for b in band):
                raise ValueError('band_hz must be two numbers')
            epoch = request.get('epoch_s', eeg_recording.DEFAULT_EPOCH_SECONDS)
            if not isinstance(epoch, (int, float)) or not .5 <= epoch <= 10:
                raise ValueError('epoch_s must be 0.5 to 10 seconds')
            label = request.get('label')
            if label is not None and (not isinstance(label, str) or len(label) > 200):
                raise ValueError('label must be text of at most 200 characters')
            result = eeg_recording.summarize(Path(request['path']), ROOT, band=tuple(band), epoch_seconds=float(epoch), label=label,
                                             progress=lambda value: progress(.05 + .9 * value, '读取、滤波并分段'))
        elif request.get('action') == 'prior':
            from compact_eeg.workflows import data_prior
            files = request.get('files')
            if set(request) != {'action', 'files'} or not isinstance(files, list) or not files or len(files) > 2000:
                raise ValueError('prior needs 1 to 2000 summary files')
            summaries = [json.loads(Path(path).read_text()) for path in files]
            result = data_prior.fit(summaries, ROOT, progress)
        else:
            raise ValueError('action must be summary or prior')
        emit({'type': 'result', 'result': result})
        return 0
    except Exception as error:
        emit({'type': 'error', 'message': str(error)})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
