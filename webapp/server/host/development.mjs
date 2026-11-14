import { createLocalComputeService } from '../local-compute-server.mjs';
import { hostConfig } from './config.mjs';

export function localComputePlugin() {
  return { name: 'eeg-local-compute', apply: 'serve',
    configureServer(server) {
      const config = hostConfig({ webappRoot: server.config.root });
      if (!config.policy.localOnly) throw new Error('Public proxy access requires the production host.');
      const service = createLocalComputeService(config.repositoryRoot, config);
      server.middlewares.use(service.middleware);
      server.httpServer?.once('close', () => service.dispose());
    } };
}
