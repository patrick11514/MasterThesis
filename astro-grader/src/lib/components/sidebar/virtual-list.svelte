<script lang="ts">
  import type { AppStateType } from '$/lib/state.svelte';
  import type { File } from '$/lib/types/File';
  import { createVirtualizer } from '@tanstack/svelte-virtual';
  import { untrack } from 'svelte';
  import Night from './night.svelte';

  type Props = {
    nights: {
      id: number;
      name: string;
      files: File[];
    }[];
    appState: AppStateType;
  };

  const { nights, appState }: Props = $props();

  let divElement = $state<HTMLDivElement | null>(null);

  let openedNights = $state<number[]>([]);

  const setNight = (id: number, opened: boolean) => {
    if (opened) {
      openedNights = [...openedNights, id];
    } else {
      openedNights = openedNights.filter((nightId) => nightId !== id);
    }
  };

  const virtualizer = $state(
    createVirtualizer({
      count: nights.length,
      getScrollElement: () => divElement,
      horizontal: true,
      estimateSize: () => 50,
      overscan: 5
    })
  );

  $effect(() => {
    const virtualizer = untrack(() => $virtualizer);
    virtualizer.setOptions({
      count: nights.length
    });
  });
</script>

<div bind:this={divElement} class="flex flex-col gap-1">
  {#each $virtualizer.getVirtualItems() as item (item.index)}
    {@const night = nights[item.index]}
    <Night {night} {appState} onToggle={(opened) => setNight(night.id, opened)} />
  {/each}
</div>
