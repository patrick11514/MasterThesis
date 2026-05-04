<script lang="ts">
  import CalibrationProgressModal from '$/lib/components/CalibrationProgressModal.svelte';
  import { Toaster } from '$/lib/components/ui/sonner';
  import { getAppStateSync } from '$/lib/state.svelte';
  import { ModeWatcher } from 'mode-watcher';
  import type { LayoutProps } from './$types';
  import './layout.css';
  const { children }: LayoutProps = $props();

  const appState = getAppStateSync();
</script>

<ModeWatcher />
<Toaster position="top-center" />
<CalibrationProgressModal
  progress={appState.calibrationProgress}
  onCancel={() => {
    void appState.cancelCalibration();
  }}
  onDone={() => {
    appState.closeCalibrationProgress();
  }}
/>

<CalibrationProgressModal
  progress={appState.metricsProgress}
  onCancel={() => {
    // No dedicated cancel for metrics currently — just close preview
    appState.closeMetricsProgress();
  }}
  onDone={() => {
    appState.closeMetricsProgress();
  }}
/>

<main class="h-screen w-screen overflow-hidden">
  {@render children?.()}
</main>
