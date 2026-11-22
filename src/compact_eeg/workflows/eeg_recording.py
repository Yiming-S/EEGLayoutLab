"""EEG recordings to band-limited spatial covariance summaries (``eeg-covariance-summary/1``).

Readers cover EDF/EDF+ and BDF/BDF+, BrainVision (.vhdr with a binary data file) and EEGLAB
(.set with embedded data or a .fdt file), using numpy and scipy only. Samples are read lazily
from memory maps, in chunks, and returned in microvolts.

A summary keeps only what the data-derived prior and channel-subset analyses use: the channels
whose names are 10-05 positions, their Ernie cap coordinates, and the average-referenced
covariance of clean epochs in one frequency band. Processing, in order:

1. channels: names normalized (``EEG `` prefix, trailing dots, ``-REF``-style suffixes, T3/T4/T5/T6)
   and matched to the SimNIBS 10-05 cap on Ernie; bipolar and unknown names are skipped;
2. filtering: 4th-order Butterworth band-pass and 50/60 Hz notches (Q 30), causal, continuous over
   each segment, initial state at the first sample; the first epoch of a segment is discarded;
3. epochs of ``epoch_seconds``; channels whose median epoch variance is flat (below 1e-6 of the
   channel median) or a robust outlier (|z| > 5 on log variance) are excluded;
4. average reference over the kept channels; epochs whose log total power has robust z above 3 or
   below -4 are rejected; the summary covariance is the mean over the remaining epochs.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re

import numpy as np
from scipy.signal import butter, iirnotch, sosfilt, sosfilt_zi, tf2sos

SUMMARY_SCHEMA = 'eeg-covariance-summary/1'
MAPPING_PATH = 'webapp/public/data/ernie-mni-mapping.json'
# '?V' is a micro sign lost by the exporter's encoding (Neuracle BDF files, for example).
UNIT_SCALE_TO_UV = {'v': 1e6, 'mv': 1e3, 'uv': 1., '?v': 1., 'nv': 1e-3}
REFERENCE_SUFFIXES = {'ref', 'le', 're', 'avg', 'ar', 'a1', 'a2', 'a12', 'm1', 'm2', 'm12', 'lm', 'rm', 'linked'}
DEFAULT_BAND_HZ = (1., 40.)
DEFAULT_EPOCH_SECONDS = 2.
NOTCH_HZ = (50., 60.)
FLAT_RATIO = 1e-6
CHANNEL_Z = 5.
# A channel is an outlier only if it is also this far from the median variance; with homogeneous channels the MAD alone flags near-median channels.
OUTLIER_RATIO = 4.
EPOCH_Z_HIGH, EPOCH_Z_LOW = 3., -4.
MEMORY_LIMIT_BYTES = 1 << 30
CHUNK_SECONDS = 30.


@dataclass
class Recording:
    """Lazily read channels; ``read`` returns microvolts, channels by rows."""
    format: str
    path: Path
    labels: list
    rates: list
    n_samples: int
    segments: list
    _read: object = field(repr=False)
    problems: dict = field(default_factory=dict)
    # EDF/BDF only: channels may have different rates, so their length follows from the records.
    records: int | None = None
    record_seconds: float | None = None

    def read(self, channels, start, stop):
        return self._read(list(channels), int(start), int(stop))

    def length_at(self, rate):
        """Sample count and segments of the channels sampled at ``rate``."""
        if self.records is None:
            return self.n_samples, self.segments
        n = self.records * int(round(rate * self.record_seconds))
        return n, [(0, n)]


def _text(raw):
    return raw.decode('latin-1').strip()


def _unit_scale(unit):
    key = (unit or '').strip().replace('µ', 'u').replace('μ', 'u').lower()
    return UNIT_SCALE_TO_UV.get(key)


def _edf(path):
    with open(path, 'rb') as f:
        head = f.read(256)
        if len(head) < 256:
            raise ValueError('EDF/BDF文件头不完整')
        bdf = head[:1] == b'\xff' and head[1:8] == b'BIOSEMI'
        if not bdf and head[:8].strip() != b'0':
            raise ValueError('不是EDF或BDF文件')
        try:
            header_bytes, records, duration, ns = int(head[184:192]), int(head[236:244]), float(head[244:252]), int(head[252:256])
        except ValueError as error:
            raise ValueError('EDF/BDF文件头字段无效') from error
        reserved = _text(head[192:236])
        if reserved.startswith(('EDF+D', 'BDF+D')):
            raise ValueError('不支持不连续的EDF+D/BDF+D记录；请导出连续数据')
        if ns < 1 or header_bytes != 256 * (ns + 1) or not duration > 0:
            raise ValueError('EDF/BDF文件头的信号数、长度或记录时长无效')
        signal = f.read(256 * ns)
    offset = 0

    def column(width, convert=_text):
        nonlocal offset
        values = [convert(signal[offset + i * width: offset + (i + 1) * width]) for i in range(ns)]
        offset += width * ns
        return values
    labels, _transducer, units = column(16), column(80), column(8)

    def number(raw):
        # A blank or malformed range makes only that channel unusable (seen in some exported files).
        try:
            return float(_text(raw))
        except ValueError:
            return np.nan
    pmin, pmax, dmin, dmax = column(8, number), column(8, number), column(8, number), column(8, number)
    try:
        _prefilter, spr = column(80), column(8, lambda raw: int(_text(raw)))
    except ValueError as error:
        raise ValueError('EDF/BDF信号头的每记录采样数无效') from error
    width = 3 if bdf else 2
    record_samples = sum(spr)
    record_bytes = record_samples * width
    available = (path.stat().st_size - header_bytes) // record_bytes
    records = available if records < 0 else min(records, available)
    if records < 1:
        raise ValueError('EDF/BDF文件没有完整的数据记录')
    starts = np.concatenate([[0], np.cumsum(spr)[:-1]])
    data = np.memmap(path, dtype=np.uint8, mode='r', offset=header_bytes, shape=(records, record_bytes))
    gains, offsets, invalid = [], [], []
    for i in range(ns):
        scale = _unit_scale(units[i])
        gain = (pmax[i] - pmin[i]) / (dmax[i] - dmin[i]) if dmax[i] != dmin[i] else np.nan
        invalid.append(not np.isfinite(gain))
        gains.append(np.nan if scale is None else gain * scale)
        offsets.append(np.nan if scale is None else (pmin[i] - dmin[i] * gain) * scale)

    def read(channels, start, stop):
        per = {spr[c] for c in channels}
        if len(per) != 1:
            raise ValueError('所读通道的采样率不同')
        per = per.pop()
        first, last = start // per, -(-stop // per)
        out = np.empty((len(channels), stop - start))
        block = data[first:last]
        for row, c in enumerate(channels):
            raw = block[:, starts[c] * width:(starts[c] + per) * width]
            if bdf:
                raw = raw.reshape(-1, 3).astype(np.int32)
                values = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
                values = np.where(values >= 1 << 23, values - (1 << 24), values)
            else:
                values = np.ascontiguousarray(raw).view('<i2').reshape(-1)
            out[row] = values[start - first * per: stop - first * per] * gains[c] + offsets[c]
        return out
    rates = [spr[i] / duration for i in range(ns)]
    annotation = [label in ('EDF Annotations', 'BDF Annotations') or not np.isfinite(gains[i]) for i, label in enumerate(labels)]
    kept = [i for i in range(ns) if not annotation[i]]
    common = Counter(spr[i] for i in kept).most_common(1)[0][0] if kept else 0
    problems = {i: 'invalid_header_range' if invalid[i] else 'unknown_unit' for i in range(ns)
                if annotation[i] and labels[i] not in ('EDF Annotations', 'BDF Annotations')}
    # n_samples and segments are at the most common rate; summarize uses length_at for the rate it reads.
    return Recording('bdf' if bdf else 'edf', path, labels, [rates[i] if not annotation[i] else 0. for i in range(ns)],
                     int(records * common), [(0, int(records * common))], read, problems, records=int(records), record_seconds=duration)


def _vhdr(path):
    raw = path.read_bytes()
    text = raw.decode('utf-8', errors='strict') if b'Codepage=UTF-8' in raw else raw.decode('latin-1')
    sections, current = {}, None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(';'):
            continue
        if line.startswith('[') and line.endswith(']'):
            current = sections.setdefault(line[1:-1].strip().lower(), {})
        elif '=' in line and current is not None:
            key, value = line.split('=', 1)
            current[key.strip().lower()] = value.strip()
    common, binary, channels = sections.get('common infos', {}), sections.get('binary infos', {}), sections.get('channel infos', {})
    if common.get('dataformat', 'BINARY').upper() != 'BINARY':
        raise ValueError('只支持二进制BrainVision数据')
    orientation = common.get('dataorientation', 'MULTIPLEXED').upper()
    if orientation not in ('MULTIPLEXED', 'VECTORIZED'):
        raise ValueError('BrainVision数据方向无效')
    dtype = {'INT_16': '<i2', 'INT_32': '<i4', 'IEEE_FLOAT_32': '<f4'}.get(binary.get('binaryformat', 'INT_16').upper())
    if dtype is None or binary.get('usebigendianorder', 'NO').upper() == 'YES':
        raise ValueError('BrainVision二进制格式不受支持')
    name = common.get('datafile', '')
    if not name or Path(name).name != name:
        raise ValueError('BrainVision数据文件须与.vhdr位于同一目录')
    data_path = path.with_name(name)
    try:
        count, interval = int(common['numberofchannels']), float(common['samplinginterval'])
    except (KeyError, ValueError) as error:
        raise ValueError('BrainVision头缺少通道数或采样间隔') from error
    labels, scales = [], []
    for i in range(1, count + 1):
        parts = channels.get(f'ch{i}', '').split(',')
        if not parts[0]:
            raise ValueError(f'BrainVision头缺少Ch{i}')
        labels.append(parts[0].replace('\\1', ','))
        resolution = float(parts[2]) if len(parts) > 2 and parts[2] else 1.
        scale = _unit_scale(parts[3] if len(parts) > 3 and parts[3] else 'uV')
        scales.append(np.nan if scale is None else resolution * scale)
    item = np.dtype(dtype).itemsize
    samples = data_path.stat().st_size // (item * count)
    shape = (samples, count) if orientation == 'MULTIPLEXED' else (count, samples)
    data = np.memmap(data_path, dtype=dtype, mode='r', shape=shape)
    scales = np.asarray(scales)

    def read(channels, start, stop):
        block = data[start:stop, channels].T if orientation == 'MULTIPLEXED' else data[channels, start:stop]
        return np.asarray(block, dtype=np.float64) * scales[channels, None]
    rate = 1e6 / interval
    return Recording('brainvision', path, labels, [rate if np.isfinite(s) else 0. for s in scales], int(samples), [(0, int(samples))], read,
                     {i: 'unknown_unit' for i, s in enumerate(scales) if not np.isfinite(s)})


def _set(path):
    from scipy.io import loadmat
    try:
        mat = loadmat(path, squeeze_me=True, struct_as_record=False, appendmat=False)
    except NotImplementedError as error:
        raise ValueError('EEGLAB v7.3（HDF5）文件请在EEGLAB中另存为v7格式') from error
    eeg = mat['EEG'] if 'EEG' in mat else type('EEG', (), {k: v for k, v in mat.items() if not k.startswith('__')})
    get = lambda name, default=None: getattr(eeg, name, default)
    count, points, trials, rate = int(get('nbchan')), int(get('pnts')), int(get('trials', 1) or 1), float(get('srate'))
    locations = np.atleast_1d(get('chanlocs', []))
    labels = [str(getattr(c, 'labels', '')).strip() for c in locations]
    if len(labels) != count or not all(labels):
        raise ValueError('EEGLAB文件缺少通道名称（chanlocs.labels）')
    data = get('data')
    total = points * trials
    if isinstance(data, str):
        if Path(data).name != data:
            raise ValueError('EEGLAB数据文件须与.set位于同一目录')
        data = np.memmap(path.with_name(data), dtype='<f4', mode='r', shape=(total, count))
        sample_major = True
    else:
        data = np.asarray(data, dtype=np.float64).reshape(count, total, order='F')
        sample_major = False
    segments = [(i * points, (i + 1) * points) for i in range(trials)]
    if trials == 1:
        events = np.atleast_1d(get('event', []))
        # A boundary at 1-based latency L (L.5 by convention) lies after 1-based sample floor(L), so the next
        # segment starts at 0-based index floor(L).
        cuts = sorted({int(np.floor(float(getattr(e, 'latency', 0)))) for e in events if str(getattr(e, 'type', '')) == 'boundary'})
        cuts = [cut for cut in cuts if 0 < cut < total]
        edges = [0, *cuts, total]
        segments = [(a, b) for a, b in zip(edges[:-1], edges[1:]) if b > a]

    def read(channels, start, stop):
        block = data[start:stop, channels].T if sample_major else data[channels, start:stop]
        return np.asarray(block, dtype=np.float64)
    return Recording('eeglab', path, labels, [rate] * count, total, segments, read)


def open_recording(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in ('.edf', '.bdf', '.rec'):
        return _edf(path)
    if suffix == '.vhdr':
        return _vhdr(path)
    if suffix == '.set':
        return _set(path)
    raise ValueError('支持EDF/BDF、BrainVision（.vhdr）和EEGLAB（.set）文件')


def cap_lookup(root):
    mapping = json.loads((Path(root) / MAPPING_PATH).read_text())
    labels = mapping['labels']
    positions = {str(label).lower(): (str(label), [float(x), float(y), float(z)]) for label, x, y, z in labels['positions_mm']}
    return positions, {k.upper(): v for k, v in labels['aliases'].items()}, mapping['mapping_id']


def cap_label(raw, positions, aliases):
    """10-05 cap label of a recorded channel name, or None for bipolar, auxiliary and unknown names."""
    name = re.sub(r'^eeg[\s_:]+', '', raw.strip(), flags=re.IGNORECASE).strip().rstrip('.').strip()
    if '-' in name:
        head, tail = name.split('-', 1)
        if tail.strip().lower() not in REFERENCE_SUFFIXES:
            return None
        name = head.strip()
    found = positions.get(aliases.get(name.upper(), name).lower())
    return found[0] if found else None


def _filter(rate, band):
    low, high = band
    if not 0 < low < high < rate / 2:
        raise ValueError(f'频带须满足 0 < 低频 < 高频 < 奈奎斯特频率（{rate / 2:g} Hz）')
    sections = [butter(4, [low, high], btype='bandpass', fs=rate, output='sos')]
    notches = [f for f in NOTCH_HZ if f < rate / 2 - 1]
    for f in notches:
        sections.append(tf2sos(*iirnotch(f, 30., fs=rate)))
    return np.vstack(sections), notches


def _robust_z(values):
    centre = np.median(values)
    spread = 1.4826 * np.median(np.abs(values - centre))
    return (values - centre) / spread if spread > 0 else np.zeros_like(values)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def summarize(path, root, *, band=DEFAULT_BAND_HZ, epoch_seconds=DEFAULT_EPOCH_SECONDS, label=None, progress=lambda *a: None):
    """Covariance summary of one recording; see the module docstring for the processing."""
    path = Path(path)
    recording = open_recording(path)
    positions, aliases, mapping_id = cap_lookup(root)
    mapped, skipped, seen = [], [], {}
    for i, raw in enumerate(recording.labels):
        cap = cap_label(raw, positions, aliases) if recording.rates[i] > 0 else None
        if cap is None:
            skipped.append({'label': raw, 'reason': 'not_a_10-05_name' if recording.rates[i] > 0 else recording.problems.get(i, 'annotation')})
        elif cap in seen:
            skipped.append({'label': raw, 'reason': f'duplicate_of_{recording.labels[seen[cap]]}'})
        else:
            seen[cap] = i
            mapped.append((i, cap))
    if not mapped:
        raise ValueError('没有可识别的10-05电极名称')
    rate = Counter(recording.rates[i] for i, _ in mapped).most_common(1)[0][0]
    for i, cap in [m for m in mapped if recording.rates[m[0]] != rate]:
        skipped.append({'label': recording.labels[i], 'reason': 'different_sampling_rate'})
    mapped = [m for m in mapped if recording.rates[m[0]] == rate]
    if len(mapped) < 8:
        raise ValueError(f'可用的10-05电极少于8个（{len(mapped)}个）')
    channels = [i for i, _ in mapped]
    sos, notches = _filter(rate, tuple(float(b) for b in band))
    step = int(round(epoch_seconds * rate))
    if step < 16:
        raise ValueError('分段太短')
    c = len(channels)
    n_samples, segments = recording.length_at(rate)
    usable = sum(max(0, (b - a) // step - 1) for a, b in segments)
    if usable < 10:
        raise ValueError('去除每段首个分段后，可用分段少于10个')
    stride = max(1, -(-usable * c * c * 8 // MEMORY_LIMIT_BYTES))
    covariances, epoch_index = [], 0
    chunk = max(1, int(CHUNK_SECONDS * rate) // step) * step
    for a, b in segments:
        if (b - a) // step < 2:
            continue
        state = None
        end = a + ((b - a) // step) * step
        for start in range(a, end, chunk):
            x = recording.read(channels, start, min(start + chunk, end))
            if state is None:
                state = sosfilt_zi(sos)[:, None, :] * x[None, :, :1]
            y, state = sosfilt(sos, x, axis=1, zi=state)
            for k in range(0, y.shape[1], step):
                if start == a and k == 0:
                    continue
                if epoch_index % stride == 0:
                    e = y[:, k:k + step]
                    e = e - e.mean(axis=1, keepdims=True)
                    covariances.append(e @ e.T / step)
                epoch_index += 1
        progress(b / n_samples)
    stack = np.asarray(covariances)
    variance = np.median(np.einsum('eii->ei', stack), axis=0)
    flat = variance < FLAT_RATIO * np.median(variance)
    log_variance = np.log(np.maximum(variance, np.finfo(float).tiny))
    outlier = (np.abs(_robust_z(np.where(flat, np.median(log_variance), log_variance))) > CHANNEL_Z) \
        & (np.abs(np.log(np.maximum(variance, np.finfo(float).tiny) / np.median(variance))) > np.log(OUTLIER_RATIO))
    good = ~(flat | outlier)
    if good.sum() < 8:
        raise ValueError('排除平坦或异常通道后少于8个通道')
    bad = [{'label': mapped[k][1], 'reason': 'flat' if flat[k] else 'variance_outlier',
            'variance_ratio_to_median': float(variance[k] / np.median(variance))} for k in np.flatnonzero(~good)]
    kept = np.flatnonzero(good)
    n = len(kept)
    centring = np.eye(n) - 1. / n
    subset = stack[:, kept][:, :, kept]
    # tr(P C P) = tr(C) - 1'C1/n, so the referenced epochs are never stored.
    total = np.einsum('eii->e', subset) - subset.sum(axis=(1, 2)) / n
    z = _robust_z(np.log(np.maximum(total, np.finfo(float).tiny)))
    accepted = (z <= EPOCH_Z_HIGH) & (z >= EPOCH_Z_LOW)
    if accepted.sum() < 10:
        raise ValueError('剔除伪迹分段后少于10个分段')
    covariance = centring @ subset[accepted].mean(axis=0) @ centring
    covariance = .5 * (covariance + covariance.T)
    labels = [mapped[k][1] for k in kept]
    return {
        'schema': SUMMARY_SCHEMA, 'label': label or path.stem,
        'source': {'format': recording.format, 'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha256(path),
                   'sampling_rate_hz': float(rate), 'duration_s': n_samples / rate, 'segment_count': len(segments)},
        'mapping_id': mapping_id, 'channels': labels, 'input_labels': [recording.labels[mapped[k][0]] for k in kept],
        'xyz_mm': [positions[name.lower()][1] for name in labels],
        'skipped_channels': skipped, 'bad_channels': bad,
        'processing': {'band_hz': [float(band[0]), float(band[1])], 'notch_hz': notches, 'epoch_s': step / rate, 'epoch_stride': stride,
                       'filter': 'butterworth order 4 band-pass and iirnotch Q 30, causal sosfilt, initial state at the first sample',
                       'transient': 'first epoch of each segment discarded', 'reference': 'average of the kept channels',
                       'channel_rule': f'flat below {FLAT_RATIO:g} of median variance, or |robust z| > {CHANNEL_Z:g} on log variance and variance beyond {OUTLIER_RATIO:g}x or 1/{OUTLIER_RATIO:g} of the median',
                       'epoch_rule': f'robust z of log total power > {EPOCH_Z_HIGH:g} or < {EPOCH_Z_LOW:g}'},
        'epochs': {'total': epoch_index, 'analysed': int(len(stack)), 'used': int(accepted.sum()), 'rejected': int((~accepted).sum())},
        'unit': 'uV^2', 'covariance': [[float(f'{v:.9g}') for v in row] for row in covariance],
    }


def check_summary(summary, root=None):
    """Structural check of a covariance summary; with ``root``, positions must match the current cap mapping."""
    if not isinstance(summary, dict) or summary.get('schema') != SUMMARY_SCHEMA:
        raise ValueError('不是eeg-covariance-summary/1文件')
    names, xyz = summary.get('channels'), np.asarray(summary.get('xyz_mm'), dtype=float)
    covariance = np.asarray(summary.get('covariance'), dtype=float)
    if not isinstance(names, list) or len(names) < 8 or len(set(names)) != len(names) or xyz.shape != (len(names), 3) \
            or covariance.shape != (len(names), len(names)) or not np.all(np.isfinite(covariance)) or not np.all(np.isfinite(xyz)):
        raise ValueError('协方差摘要的通道、坐标或矩阵无效')
    if not np.allclose(covariance, covariance.T, rtol=1e-6, atol=1e-9 * np.abs(covariance).max()):
        raise ValueError('协方差矩阵不对称')
    if np.abs(covariance.sum(axis=1)).max() > 1e-5 * np.trace(covariance):
        raise ValueError('协方差须为平均参考')
    if np.linalg.eigvalsh(covariance).min() < -1e-6 * np.trace(covariance):
        raise ValueError('协方差矩阵不是半正定')
    if root is not None:
        positions, _aliases, mapping_id = cap_lookup(root)
        if summary.get('mapping_id') != mapping_id or any(positions.get(str(n).lower(), (None, None))[0] != n for n in names) \
                or not np.allclose(xyz, [positions[n.lower()][1] for n in names], atol=1e-9):
            raise ValueError('协方差摘要的电极坐标与当前10-05帽映射不一致')
    return summary


__all__ = ['SUMMARY_SCHEMA', 'Recording', 'open_recording', 'cap_lookup', 'cap_label', 'summarize', 'check_summary']
