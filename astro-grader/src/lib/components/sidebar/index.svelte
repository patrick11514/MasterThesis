<script lang="ts">
  import { getAppState } from '$/lib/state.svelte';
  import RawNights from './raw-nights.svelte';

  const appState = await getAppState();
</script>

{#if 'PreviewNights' in appState.files}
  <RawNights {appState} nights={appState.files.PreviewNights} />
{/if}
