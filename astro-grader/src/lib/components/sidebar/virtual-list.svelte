<script lang="ts">
  import type { AppStateType } from '$/lib/state.svelte';
  import type { File } from '$/lib/types/File';
  import { createVirtualizer } from '@tanstack/svelte-virtual';
  import { untrack } from 'svelte';
  import FileElement from './file.svelte';
  import NightElement from './night.svelte';

  type Night = {
    id: number;
    name: string;
    files: File[];
  };

  type Props = {
    nights: Night[];
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

  type NightFile = {
    file: File;
    night: string;
  };

  type Element =
    | ({
        _type: 'night';
      } & Night)
    | ({
        _type: 'file';
      } & NightFile);

  const virtualElements = $derived.by<Element[]>(() => {
    const elements: Element[] = [];

    for (const night of nights) {
      const files = night.files.filter((file) => appState.framesShown[file.type]);
      if (files.length === 0) continue;

      elements.push({
        _type: 'night',
        ...night
      });

      if (openedNights.includes(night.id)) {
        elements.push(
          ...night.files
            .filter((file) => appState.framesShown[file.type])
            .map(
              (file) =>
                ({
                  _type: 'file',
                  file,
                  night: night.name
                }) as const
            )
        );
      }
    }

    return elements;
  });

  const virtualizer = $state(
    createVirtualizer({
      // svelte-ignore state_referenced_locally - we can't everytime re-create virtualizer, so we have effect under it, to update the count
      count: virtualElements.length,
      getScrollElement: () => divElement,
      estimateSize: () => 35,
      overscan: 10
    })
  );

  $effect(() => {
    const virtualizer = untrack(() => $virtualizer);
    virtualizer.setOptions({
      count: virtualElements.length
    });
  });
</script>

<div bind:this={divElement} class="relative h-full overflow-y-auto">
  <div style="height: {$virtualizer.getTotalSize()}px; width: 100%; position: relative;">
    {#each $virtualizer.getVirtualItems() as _item (_item.index)}
      {@const item = virtualElements[_item.index]}
      {#if item}
        <div
          style="position: absolute; top: 0; left: 0; width: 100%; transform: translateY({_item.start}px);"
        >
          {#if item._type === 'night'}
            {@const night = item as Night}
            <NightElement
              {night}
              {appState}
              opened={openedNights.includes(item.id)}
              onToggle={(opened) => setNight(item.id, opened)}
            />
          {:else}
            {@const { file, night } = item as NightFile}
            <FileElement {file} {night} {appState} />
          {/if}
        </div>
      {/if}
    {/each}
  </div>
</div>
