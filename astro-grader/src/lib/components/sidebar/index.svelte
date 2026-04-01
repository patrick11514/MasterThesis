<script lang="ts">
  import { FILE_BADGES } from '$/lib/files/types';
  import { getAppState } from '../../state.svelte';
  import { Badge } from '../ui/badge';
  import * as Resizable from '../ui/resizable';
  import FileImport from './file-import.svelte';
  import NightConfig from './night-config.svelte';
  import Night from './night.svelte';
  import { isShown } from './utils';

  const appState = await getAppState();
</script>

<Resizable.Pane defaultSize={20} class="flex flex-col items-center gap-2 p-2">
  <FileImport />

  <NightConfig />

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

  <div class="flex w-full flex-col gap-2 overflow-y-auto">
    {#if Object.keys(appState.files).length === 0}
      <p class="text-center text-muted-foreground">No files imported.</p>
    {:else}
      {#each Object.entries(appState.files) as [night, files] (night)}
        {#if files.filter((file) => isShown(appState, file)).length > 0}
          <Night {night} {files} {appState} />
        {/if}
      {/each}
    {/if}
  </div>
</Resizable.Pane>
