/** Local OS access controls maintenance; browser session tokens cannot toggle it. */
export function installOperatorSignals(service, { target = process, log = console.log } = {}) {
  const change = enabled => {
    try { log(JSON.stringify({ event: 'maintenance', ...service.scheduler.setMaintenance(enabled) })); }
    catch (error) { log(JSON.stringify({ event: 'maintenance_error', message: error.message })); }
  };
  const pause = () => change(true), resume = () => change(false);
  target.on('SIGUSR2', pause); target.on('SIGUSR1', resume);
  return () => { target.off('SIGUSR2', pause); target.off('SIGUSR1', resume); };
}
