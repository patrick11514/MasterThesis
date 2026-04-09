<script lang="ts">
  import { getAppState } from '$/lib/state.svelte';
  import GroupedNights from './grouped-nights.svelte';
  import RawNights from './raw-nights.svelte';

  const appState = await getAppState();
</script>

{#if 'PreviewNights' in appState.files}
  <RawNights {appState} nights={appState.files.PreviewNights} />
{:else if 'GroupedNights' in appState.files}
  <GroupedNights nights={appState.files.GroupedNights} />
{/if}
