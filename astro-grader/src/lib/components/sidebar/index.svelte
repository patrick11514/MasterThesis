<script lang="ts">
  import { FILE_BADGES } from '$/lib/files/types';
  import { getAppState } from '../../state.svelte';
  import { Badge } from '../ui/badge';
  import * as Resizable from '../ui/resizable';
  import FileImport from './file-import.svelte';
  import Header from './header.svelte';
  import VirtualList from './virtual-list.svelte';

  const appState = await getAppState();

  const nights = $derived(
    Object.entries(appState.rawNights).map(([night, files], idx) => ({
      id: idx,
      name: night,
      files
    }))
  );
</script>

<Resizable.Pane defaultSize={20} class="flex flex-col items-center p-2">
  <Header />
  <FileImport />

  <h2 class="text-lg">Night list</h2>

  <div class="flex w-full flex-wrap items-center justify-center gap-2">
    {#each Object.entries(appState.framesShown) as [type, shown] (type)}
      <Badge
        onclick={() => {
          appState.framesShown[type] = !appState.framesShown[type];
        }}
        variant="outline"
        class={{
          [FILE_BADGES[type]]: true,
          'line-through': !shown,
          'cursor-pointer': true
        }}
      >
        {type}
      </Badge>
    {/each}
  </div>

  <div class="h-full min-h-0 w-full flex-1">
    {#if Object.keys(appState.rawNights).length === 0}
      <p class="text-center text-muted-foreground">No files imported.</p>
    {:else}
      <VirtualList {nights} {appState} />
    {/if}
  </div>
</Resizable.Pane>
