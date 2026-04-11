<script lang="ts">
  import { getAppState } from '$/lib/state.svelte';
  import RawNights from './raw-nights.svelte';

  const appState = await getAppState();
</script>

<RawNights {appState} nights={appState.rawNights} />
