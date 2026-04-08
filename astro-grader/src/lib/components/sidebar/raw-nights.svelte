<script lang="ts">
  import { FILE_BADGES } from '$/lib/files/types';
  import type { Nights } from '$/lib/types/Nights';
  import { type AppStateType } from '../../state.svelte';
  import { Badge } from '../ui/badge';
  import * as Resizable from '../ui/resizable';
  import FileImport from './file-import.svelte';
  import NightConfig from './night-config.svelte';
  import VirtualList from './virtual-list.svelte';

  type ExtractPreview<Raw> = Raw extends { PreviewNights: infer T } ? T : never;

  type Props = {
    nights: ExtractPreview<Nights>;
    appState: AppStateType;
  };
  const { nights: rawNights, appState }: Props = $props();

  const nights = $derived(
    Object.entries(rawNights).map(([night, files], idx) => ({
      id: idx,
      name: night,
      files
    }))
  );

  $effect(() => {
    console.log('outside');
    console.log(nights);
  });
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

  <div class="h-full min-h-0 w-full flex-1">
    {#if Object.keys(appState.files).length === 0}
      <p class="text-center text-muted-foreground">No files imported.</p>
    {:else}
      <VirtualList {nights} {appState} />
    {/if}
  </div>
</Resizable.Pane>
