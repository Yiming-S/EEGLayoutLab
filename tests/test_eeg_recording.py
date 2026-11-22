"""EEG readers and covariance summaries on synthetic EDF, BDF, BrainVision and EEGLAB files."""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat
from scipy.signal import sosfilt, sosfilt_zi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from compact_eeg.workflows import eeg_recording as er

LABELS = ['Fp1', 'Fp2', 'F3', 'F4', 'C3', 'C4', 'P3', 'P4', 'O1', 'O2', 'Fz', 'Cz', 'Pz', 'T7', 'T8']
RATE = 250


def signals(seconds=60, seed=0, channels=len(LABELS)):
    rng = np.random.default_rng(seed)
    mixing = rng.normal(size=(channels, channels))
    return mixing @ rng.normal(size=(channels, seconds * RATE)) * 10 + rng.normal(size=(channels, 1)) * 200


def write_edf(path, labels, data, *, bdf=False, units='uV', annotation=False):
    """Minimal EDF/BDF writer: 1 s records, per-channel symmetric physical range."""
    ns, spr = len(labels) + annotation, RATE
    records = data.shape[1] // spr
    dmin, dmax = (-(1 << 23), (1 << 23) - 1) if bdf else (-32768, 32767)
    peak = np.abs(data).max(axis=1) * 1.01 + 1e-9
    digital = np.round((data[:, :records * spr] + peak[:, None]) / (2 * peak[:, None]) * (dmax - dmin) + dmin).astype(np.int64)
    pad = lambda value, width: str(value).encode('latin-1').ljust(width)[:width]
    head = (b'\xffBIOSEMI' if bdf else pad(0, 8)) + pad('X', 80) + pad('X', 80) + pad('01.01.24', 8) + pad('00.00.00', 8)
    head += pad(256 * (ns + 1), 8) + pad('24BIT' if bdf else ('EDF+C' if annotation else ''), 44) + pad(records, 8) + pad(1, 8) + pad(ns, 4)
    names = labels + (['EDF Annotations'] if annotation else [])
    column = lambda values, width: b''.join(pad(v, width) for v in values)
    head += column(names, 16) + column([''] * ns, 80) + column([units] * len(labels) + ([''] if annotation else []), 8)
    head += column([f'{-p:.6g}' for p in peak] + (['-1'] if annotation else []), 8) + column([f'{p:.6g}' for p in peak] + (['1'] if annotation else []), 8)
    head += column([dmin] * ns, 8) + column([dmax] * ns, 8) + column([''] * ns, 80) + column([spr] * len(labels) + ([4] if annotation else []), 8)
    head += column([''] * ns, 32)
    body = bytearray()
    for r in range(records):
        for c in range(len(labels)):
            values = digital[c, r * spr:(r + 1) * spr]
            if bdf:
                body += np.stack([values & 255, (values >> 8) & 255, (values >> 16) & 255], axis=1).astype(np.uint8).tobytes()
            else:
                body += values.astype('<i2').tobytes()
        if annotation:
            body += b'+0\x14\x14\x00'.ljust(4 * (3 if bdf else 2), b'\x00')
    path.write_bytes(head + bytes(body))
    gain = 2 * peak / (dmax - dmin)
    return (digital - dmin) * gain[:, None] - peak[:, None]


def write_brainvision(path, labels, data, resolution=.1):
    digital = np.round(data / resolution).astype('<i2')
    path.with_suffix('.eeg').write_bytes(digital.T.tobytes())
    channels = '\n'.join(f'Ch{i + 1}={name},,{resolution},µV' for i, name in enumerate(labels))
    path.write_text('Brain Vision Data Exchange Header File Version 1.0\n\n[Common Infos]\nCodepage=UTF-8\n'
                    f'DataFile={path.with_suffix(".eeg").name}\nMarkerFile={path.with_suffix(".vmrk").name}\nDataFormat=BINARY\n'
                    f'DataOrientation=MULTIPLEXED\nNumberOfChannels={len(labels)}\nSamplingInterval={1e6 / RATE:g}\n\n'
                    f'[Binary Infos]\nBinaryFormat=INT_16\n\n[Channel Infos]\n{channels}\n', encoding='utf-8')
    path.with_suffix('.vmrk').write_text('Brain Vision Data Exchange Marker File, Version 1.0\n\n[Common Infos]\nCodepage=UTF-8\n'
                                         f'DataFile={path.with_suffix(".eeg").name}\n\n[Marker Infos]\nMk1=New Segment,,1,1,0\n', encoding='utf-8')
    return digital.astype(float) * resolution


def write_eeglab(path, labels, data, *, fdt=False, boundaries=()):
    locations = np.zeros((1, len(labels)), dtype=[('labels', 'O'), ('X', 'O'), ('Y', 'O'), ('Z', 'O'), ('type', 'O')])
    for i, name in enumerate(labels):
        locations[0, i] = (name, np.array([]), np.array([]), np.array([]), 'EEG')
    events = np.zeros((1, len(boundaries)), dtype=[('type', 'O'), ('latency', 'O'), ('duration', 'O')])
    for i, latency in enumerate(boundaries):
        events[0, i] = ('boundary', float(latency), 0.)
    values = data.astype(np.float32)
    if fdt:
        path.with_suffix('.fdt').write_bytes(values.T.tobytes())
    eeg = {'setname': 'test', 'nbchan': float(len(labels)), 'pnts': float(data.shape[1]), 'trials': 1., 'srate': float(RATE),
           'xmin': 0., 'xmax': (data.shape[1] - 1) / RATE, 'times': np.array([]), 'chanlocs': locations, 'event': events,
           'data': path.with_suffix('.fdt').name if fdt else values, 'icawinv': np.array([]), 'icasphere': np.array([]),
           'icaweights': np.array([]), 'icaact': np.array([]), 'epoch': np.array([]), 'ref': 'common', 'chaninfo': {'plotrad': np.array([])},
           'urevent': np.array([]), 'eventdescription': np.array([]), 'epochdescription': np.array([]), 'specdata': np.array([]),
           'reject': {'rejjp': np.array([])}, 'stats': {'jp': np.array([])}, 'history': '', 'saved': 'no', 'etc': {'eeglabvers': '2024.0'}, 'filename': path.name, 'filepath': str(path.parent)}
    savemat(path, {'EEG': eeg}, appendmat=False)
    return values.astype(float)


@pytest.mark.parametrize('kind', ['edf', 'bdf', 'edf_annotated', 'brainvision', 'eeglab', 'eeglab_fdt'])
def test_readers_return_the_written_microvolts(tmp_path, kind):
    data = signals(seconds=12)
    if kind.startswith('edf') or kind == 'bdf':
        path = tmp_path / ('x.bdf' if kind == 'bdf' else 'x.edf')
        expected = write_edf(path, LABELS, data, bdf=kind == 'bdf', annotation=kind == 'edf_annotated')
    elif kind == 'brainvision':
        path = tmp_path / 'x.vhdr'
        expected = write_brainvision(path, LABELS, data)
    else:
        path = tmp_path / 'x.set'
        expected = write_eeglab(path, LABELS, data, fdt=kind == 'eeglab_fdt')
    recording = er.open_recording(path)
    assert recording.labels[:len(LABELS)] == LABELS and recording.n_samples == 12 * RATE
    channels = [0, 3, 7]
    assert np.allclose(recording.read(channels, 0, 12 * RATE), expected[channels], rtol=0, atol=1e-6 * np.abs(expected).max())
    assert np.allclose(recording.read([5], 777, 1555), expected[[5], 777:1555], rtol=0, atol=1e-6 * np.abs(expected).max())
    if kind == 'edf_annotated':
        assert recording.rates[-1] == 0


def test_edf_units_scale_to_microvolts(tmp_path):
    data = signals(seconds=4)
    write_edf(tmp_path / 'uv.edf', LABELS, data)
    write_edf(tmp_path / 'mv.edf', LABELS, data / 1000, units='mV')
    microvolts = er.open_recording(tmp_path / 'uv.edf').read([0], 0, 4 * RATE)
    assert np.allclose(er.open_recording(tmp_path / 'mv.edf').read([0], 0, 4 * RATE), microvolts, rtol=0, atol=1e-5 * np.abs(microvolts).max())


def test_channel_names_are_normalized_to_cap_labels():
    positions, aliases, _ = er.cap_lookup(ROOT)
    cases = {'Fp1': 'Fp1', 'EEG Fp1-REF': 'Fp1', 'Fc5.': 'FC5', 'Fcz.': 'FCz', 'T3': 'T7', 't5': 'P7', 'EEG C3-LE': 'C3',
             'CZ': 'Cz', 'Fp1-F3': None, 'EOG': None, 'Status': None, 'A1': 'A1', 'Iz..': 'Iz'}
    for raw, expected in cases.items():
        assert er.cap_label(raw, positions, aliases) == expected, raw


def reference_summary(data, band=(1, 40), epoch=2.):
    """Direct implementation of the documented processing, without chunking or rejection."""
    sos, _ = er._filter(RATE, band)
    y = sosfilt(sos, data, axis=1, zi=sosfilt_zi(sos)[:, None, :] * data[None, :, :1])[0]
    step = int(epoch * RATE)
    n = data.shape[0]
    centring = np.eye(n) - 1 / n
    epochs = [y[:, k:k + step] - y[:, k:k + step].mean(axis=1, keepdims=True) for k in range(step, data.shape[1] - step + 1, step)]
    return centring @ np.mean([e @ e.T / step for e in epochs], axis=0) @ centring


def test_summary_matches_the_direct_computation_and_is_chunk_invariant(tmp_path, monkeypatch):
    data = signals(seconds=80)
    write_edf(tmp_path / 's.edf', LABELS, data)
    expected = er.open_recording(tmp_path / 's.edf').read(range(len(LABELS)), 0, 80 * RATE)
    summary = er.summarize(tmp_path / 's.edf', ROOT, label='s')
    assert summary['channels'] == LABELS and summary['epochs']['rejected'] == 0 and summary['epochs']['used'] == 39
    written = (tmp_path / 's.edf').read_bytes()
    digest = hashlib.sha256(written).hexdigest()
    source = summary['source']
    assert source['sha256'] == source['recording_sha256'] == digest
    assert source['files'] == [{'role': 'entry', 'file': 's.edf', 'bytes': len(written), 'sha256': digest}]
    covariance = np.asarray(summary['covariance'])
    direct = reference_summary(expected)
    assert np.abs(covariance - direct).max() < 1e-8 * np.abs(direct).max()
    assert np.abs(covariance.sum(axis=1)).max() < 1e-9 * np.trace(covariance)
    monkeypatch.setattr(er, 'CHUNK_SECONDS', 6.)
    again = np.asarray(er.summarize(tmp_path / 's.edf', ROOT)['covariance'])
    assert np.abs(again - covariance).max() < 1e-9 * np.abs(covariance).max()
    er.check_summary(summary, ROOT)
    legacy = {**summary, 'source': {k: v for k, v in source.items() if k not in ('recording_sha256', 'files')}}
    assert er.check_summary(legacy, ROOT) == legacy
    assert summary['xyz_mm'][LABELS.index('Cz')] == next(p[1:] for p in __import__('json').loads(
        (ROOT / er.MAPPING_PATH).read_text())['labels']['positions_mm'] if p[0] == 'Cz')


@pytest.mark.parametrize(('extension', 'sidecar', 'dtype'), [('.vhdr', '.eeg', '<i2'), ('.set', '.fdt', '<f4')])
def test_summary_identifies_external_sample_files(tmp_path, extension, sidecar, dtype):
    path = tmp_path / ('recording' + extension)
    data = signals(seconds=40)
    if extension == '.vhdr':
        write_brainvision(path, LABELS, data)
    else:
        write_eeglab(path, LABELS, data, fdt=True)
    sample_path = path.with_suffix(sidecar)
    original = er.summarize(path, ROOT)
    source = original['source']
    written = [path.read_bytes(), sample_path.read_bytes()]
    assert source['files'] == [
        {'role': role, 'file': p.name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        for role, p, raw in zip(('entry', 'samples'), (path, sample_path), written)
    ]
    assert source['sha256'] == source['files'][0]['sha256'] != source['recording_sha256']
    assert source['bytes'] == len(written[0])

    # The same consumed bytes under another directory have the same identity. The BrainVision
    # marker is intentionally absent because covariance processing reads only the header and samples.
    moved = tmp_path / 'moved'
    moved.mkdir()
    for p, raw in zip((path, sample_path), written):
        (moved / p.name).write_bytes(raw)
    assert er.summarize(moved / path.name, ROOT)['source'] == source

    samples = np.frombuffer(written[1], dtype=dtype).copy()
    samples *= 2
    sample_path.write_bytes(samples.tobytes())
    changed = er.summarize(path, ROOT)
    assert changed['source']['sha256'] == source['sha256']
    assert changed['source']['files'][1]['sha256'] != source['files'][1]['sha256']
    assert changed['source']['recording_sha256'] != source['recording_sha256']
    assert np.allclose(changed['covariance'], np.asarray(original['covariance']) * 4)


def test_flat_channels_and_artifact_epochs_are_excluded(tmp_path):
    data = signals(seconds=80, seed=2)
    data[LABELS.index('O2')] = 5.
    data[:, 40 * RATE:42 * RATE] += 4000 * np.sin(np.linspace(0, 60 * np.pi, 2 * RATE))
    write_edf(tmp_path / 'bad.edf', LABELS, data)
    summary = er.summarize(tmp_path / 'bad.edf', ROOT)
    assert 'O2' not in summary['channels'] and summary['bad_channels'][0]['label'] == 'O2' and summary['bad_channels'][0]['reason'] == 'flat'
    assert summary['epochs']['rejected'] >= 1


def test_variance_outliers_need_a_large_ratio_as_well_as_a_robust_z(tmp_path):
    # Equal independent channels make the MAD of log variance tiny, so a robust z alone would flag a channel at 1.3x the median.
    data = np.random.default_rng(5).normal(size=(len(LABELS), 80 * RATE)) * 10
    data[LABELS.index('Fp1')] *= 1.15
    data[LABELS.index('T8')] *= 6
    write_edf(tmp_path / 'even.edf', LABELS, data)
    summary = er.summarize(tmp_path / 'even.edf', ROOT)
    assert [(b['label'], b['reason']) for b in summary['bad_channels']] == [('T8', 'variance_outlier')]
    assert 'Fp1' in summary['channels'] and summary['bad_channels'][0]['variance_ratio_to_median'] > 30


def write_mixed_edf(path, labels, data, extra_rate, extra_count=12):
    """EDF with the EEG channels at RATE and ``extra_count`` auxiliary channels at ``extra_rate`` (1 s records, +-1000 uV)."""
    rates = [RATE] * len(labels) + [extra_rate] * extra_count
    names, records = labels + [f'AUX{i}' for i in range(extra_count)], data.shape[1] // RATE
    pad = lambda value, width: str(value).encode('latin-1').ljust(width)[:width]
    column = lambda values, width: b''.join(pad(v, width) for v in values)
    ns = len(names)
    head = pad(0, 8) + pad('X', 80) + pad('X', 80) + pad('01.01.24', 8) + pad('00.00.00', 8) + pad(256 * (ns + 1), 8) + pad('', 44)
    head += pad(records, 8) + pad(1, 8) + pad(ns, 4) + column(names, 16) + column([''] * ns, 80) + column(['uV'] * ns, 8)
    head += column([-1000] * ns, 8) + column([1000] * ns, 8) + column([-32768] * ns, 8) + column([32767] * ns, 8) + column([''] * ns, 80)
    head += column(rates, 8) + column([''] * ns, 32)
    gain = 2000 / 65535
    digital = np.clip(np.round((data + 1000) / gain - 32768), -32768, 32767).astype('<i2')
    aux = np.zeros(extra_rate, dtype='<i2').tobytes()
    body = b''.join(b''.join(digital[c, r * RATE:(r + 1) * RATE].tobytes() for c in range(len(labels))) + aux * extra_count for r in range(records))
    path.write_bytes(head + body)


@pytest.mark.parametrize('extra_rate', [RATE // 2, RATE * 2])
def test_edf_channels_at_other_rates_do_not_change_the_eeg_length(tmp_path, extra_rate):
    # Many auxiliary channels at another rate used to set the length: half the recording was read, or reading failed.
    data = np.random.default_rng(3).normal(size=(len(LABELS), 60 * RATE)) * 20
    write_mixed_edf(tmp_path / 'eeg.edf', LABELS, data, RATE)
    write_mixed_edf(tmp_path / 'mixed.edf', LABELS, data, extra_rate)
    plain, mixed = er.summarize(tmp_path / 'eeg.edf', ROOT), er.summarize(tmp_path / 'mixed.edf', ROOT)
    assert mixed['source']['duration_s'] == 60 and mixed['epochs'] == plain['epochs']
    assert mixed['covariance'] == plain['covariance']
    assert {s['reason'] for s in mixed['skipped_channels']} == {'not_a_10-05_name'}


def test_eeglab_boundaries_split_segments(tmp_path):
    data = signals(seconds=40)
    write_eeglab(tmp_path / 'b.set', LABELS, data, boundaries=[20 * RATE + .5])
    recording = er.open_recording(tmp_path / 'b.set')
    assert recording.segments == [(0, 20 * RATE), (20 * RATE, 40 * RATE)]
    # Each segment loses its first epoch: 2 x (10 - 1).
    assert er.summarize(tmp_path / 'b.set', ROOT)['epochs']['total'] == 18
    # The next segment starts at 0-based floor(latency); Python's round would put 1.5 at 2.
    write_eeglab(tmp_path / 'c.set', LABELS, data, boundaries=[20 * RATE + 1.5])
    assert er.open_recording(tmp_path / 'c.set').segments == [(0, 20 * RATE + 1), (20 * RATE + 1, 40 * RATE)]


def test_unsupported_inputs_are_explained(tmp_path):
    (tmp_path / 'x.txt').write_text('')
    with pytest.raises(ValueError, match='支持'):
        er.open_recording(tmp_path / 'x.txt')
    data = signals(seconds=12)
    write_edf(tmp_path / 'd.edf', LABELS, data)
    raw = bytearray((tmp_path / 'd.edf').read_bytes())
    raw[192:197] = b'EDF+D'
    (tmp_path / 'd.edf').write_bytes(bytes(raw))
    with pytest.raises(ValueError, match='EDF\\+D'):
        er.open_recording(tmp_path / 'd.edf')
    write_edf(tmp_path / 'b.edf', ['EOG1', 'EOG2', 'X1', 'X2', 'X3', 'X4', 'X5', 'X6', 'X7'], data[:9])
    with pytest.raises(ValueError, match='10-05'):
        er.summarize(tmp_path / 'b.edf', ROOT)
    write_edf(tmp_path / 'g.edf', LABELS, data)
    with pytest.raises(ValueError, match='奈奎斯特'):
        er.summarize(tmp_path / 'g.edf', ROOT, band=(1, 200))


@pytest.mark.parametrize('kind', ['edf', 'bdf', 'brainvision', 'eeglab'])
def test_readers_agree_with_mne(tmp_path, kind):
    mne = pytest.importorskip('mne')
    data = signals(seconds=10, seed=5)
    if kind in ('edf', 'bdf'):
        path = tmp_path / f'm.{kind}'
        write_edf(path, LABELS, data, bdf=kind == 'bdf')
        raw = mne.io.read_raw_bdf(path, preload=True, verbose='error') if kind == 'bdf' else mne.io.read_raw_edf(path, preload=True, verbose='error')
    elif kind == 'brainvision':
        path = tmp_path / 'm.vhdr'
        write_brainvision(path, LABELS, data)
        raw = mne.io.read_raw_brainvision(path, preload=True, verbose='error')
    else:
        path = tmp_path / 'm.set'
        write_eeglab(path, LABELS, data, fdt=True)
        raw = mne.io.read_raw_eeglab(path, preload=True, verbose='error')
    ours = er.open_recording(path).read(range(len(LABELS)), 0, 10 * RATE)
    theirs = raw.get_data(picks=LABELS) * 1e6
    assert np.abs(ours - theirs).max() <= 1e-6 * np.abs(theirs).max()


def test_a_blank_header_range_skips_only_that_channel(tmp_path):
    data = signals(seconds=30)
    write_edf(tmp_path / 'r.edf', LABELS, data)
    raw = bytearray((tmp_path / 'r.edf').read_bytes())
    ns = len(LABELS)
    offset = 256 + (16 + 80 + 8) * ns + 8 * LABELS.index('T8')
    raw[offset:offset + 8] = b' ' * 8
    (tmp_path / 'r.edf').write_bytes(bytes(raw))
    summary = er.summarize(tmp_path / 'r.edf', ROOT)
    assert 'T8' not in summary['channels'] and len(summary['channels']) == ns - 1
    assert {'label': 'T8', 'reason': 'invalid_header_range'} in summary['skipped_channels']
