import { createHash } from 'node:crypto';
import { createReadStream, realpathSync } from 'node:fs';
import { readFile, realpath, stat } from 'node:fs/promises';
import { join, resolve, sep } from 'node:path';

/** Avoid hashing a large bank on every hit; inode/size/mtime/ctime changes force a new byte check. */
export class InputIntegrity {
  constructor(root) { this.root = realpathSync(resolve(root)); this.memo = new Map(); }
  async digest(relativePath) {
    const path = await realpath(resolve(this.root, relativePath));
    if (!path.startsWith(this.root + sep)) throw new Error('输入文件超出本项目');
    const before = await stat(path), stamp = `${before.dev}:${before.ino}:${before.size}:${before.mtimeMs}:${before.ctimeMs}`;
    if (this.memo.get(path)?.stamp === stamp) return this.memo.get(path).digest;
    const hash = createHash('sha256');
    for await (const chunk of createReadStream(path)) hash.update(chunk);
    const after = await stat(path);
    if (`${after.dev}:${after.ino}:${after.size}:${after.mtimeMs}:${after.ctimeMs}` !== stamp) throw new Error('输入文件正在变化');
    const digest = hash.digest('hex'); this.memo.set(path, { stamp, digest }); return digest;
  }
  async verify(provenance) {
    const pointerPath = 'results/v2/current_multiregion_bank.json';
    const pointer = JSON.parse(await readFile(join(this.root, pointerPath), 'utf8'));
    if (!provenance || provenance.bank_path !== pointer.path || provenance.geometry_path !== pointer.candidates || provenance.bank_sha256 !== pointer.sha256) throw new Error('缓存前向模型身份不一致');
    const entries = [[pointerPath, provenance.pointer_sha256], [pointer.path, provenance.bank_sha256],
      [pointer.candidates, provenance.geometry_sha256], [pointer.report, provenance.bank_report_sha256]];
    if (provenance.algorithm_version?.startsWith('strict-radius-local/3')) {
      const admission = JSON.parse(await readFile(join(this.root, 'results/v2/current_surface_admissibility.json'), 'utf8'));
      if (admission.path !== provenance.surface_admissibility_path || admission.sha256 !== provenance.surface_admissibility_sha256 || admission.schema_version !== provenance.surface_admissibility_version) throw new Error('外部表面筛选版本已改变，请重新计算');
      entries.push([admission.path, admission.sha256]);
    }
    for (const [path, expected] of entries) {
      if (!/^[a-f0-9]{64}$/.test(expected) || await this.digest(path) !== expected) throw new Error('本地前向数据发生变化，不能使用旧缓存；请核对模型文件');
    }
  }
}
