<script lang="ts">
  import type { AppStateType } from '$/lib/state.svelte';
  import type { File } from '$/lib/types/File';
  import { cn } from '$/lib/utils';
  import { ChevronRightIcon, InfoIcon, XIcon } from '@lucide/svelte';
  import { Button } from '../ui/button';
  import * as Popover from '../ui/popover';

  interface Props {
    night: {
      id: number;
      name: string;
      files: File[];
    };
    appState: AppStateType;
    onToggle?: (state: boolean) => void;
    opened?: boolean;
  }
  let { night, appState, onToggle, opened = false }: Props = $props();

  //calculate file types count
  const fileTypesCount = $derived(
    night.files.reduce(
      (acc, file) => {
        acc[file.type] = (acc[file.type] || 0) + 1;
        return acc;
      },
      {} as Record<string, number>
    )
  );
</script>

<button
  onclick={() => {
    opened = !opened;
    onToggle?.(opened);
  }}
  class="flex w-full items-center justify-between gap-2"
>
  <div class="flex items-center gap-2">
    <ChevronRightIcon class={cn('h-4 w-4 transition-all duration-150', { 'rotate-90': opened })} />
    {night.name}
  </div>
  <div class="flex items-center gap-2">
    <Popover.Root>
      <Popover.Trigger class="shrink-0" onclick={(ev) => ev.stopPropagation()}>
        <Button variant="outline" size="icon-sm">
          <InfoIcon />
        </Button>
      </Popover.Trigger>
      <Popover.Content class="flex w-max flex-col gap-2">
        {#each Object.entries(fileTypesCount) as [type, count] (type)}
          <div>
            <strong>{type}:</strong>
            {count}
          </div>
        {/each}
      </Popover.Content>
    </Popover.Root>
    <Button
      variant="destructive"
      size="icon-sm"
      onclick={(ev) => {
        ev.stopPropagation();

        appState.removeFiles(night.name);
      }}
    >
      <XIcon class="h-4 w-4" />
    </Button>
  </div>
</button>
