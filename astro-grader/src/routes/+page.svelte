<script lang="ts">
  import Command from '$/lib/components/command/index.svelte';
  import GroupedSessionsPanel from '$/lib/components/grouped-sessions-panel.svelte';
  import MainUi from '$/lib/components/main-ui.svelte';
  import * as Resizable from '$/lib/components/ui/resizable';
  import { getAppState } from '$/lib/state.svelte';

  const appState = await getAppState();
</script>

<Command />

<Resizable.PaneGroup direction="vertical" class="flex flex-col" autoSaveId="main-layout">
  <MainUi />
  {#if appState.groupedNights.length > 0}
    <Resizable.Handle />
    <Resizable.Pane defaultSize={30} minSize={20}>
      <GroupedSessionsPanel />
    </Resizable.Pane>
  {/if}
</Resizable.PaneGroup>
