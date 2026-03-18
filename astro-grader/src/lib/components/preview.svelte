<script lang="ts">
  import { getAppState } from '../state.svelte';
  import * as Resizable from './ui/resizable';

  const appState = await getAppState();
</script>

<Resizable.Pane defaultSize={80}>{JSON.stringify(appState.config)}</Resizable.Pane>
