<script lang="ts">
  import type { AppStateType } from '$/lib/state.svelte';
  import type { File } from '$/lib/types/File';
  import { ChevronDownIcon, ChevronUpIcon, InfoIcon, XIcon } from '@lucide/svelte';
  import { Button } from '../ui/button';
  import * as Collapsible from '../ui/collapsible';
  import * as Popover from '../ui/popover';
  import FileComponent from './file.svelte';

  interface Props {
    night: string;
    files: File[];
    appState: AppStateType;
  }
  const { night, files, appState }: Props = $props();

  let opened = $state(false);

  const isShown = (file: File) => {
    const type = file.type;
    return appState.framesShown[type];
  };

  //calculate file types count
  const fileTypesCount = $derived(
    files.reduce(
      (acc, file) => {
        acc[file.type] = (acc[file.type] || 0) + 1;
        return acc;
      },
      {} as Record<string, number>
    )
  );
</script>

<Collapsible.Root
  onOpenChangeComplete={(open) => {
    opened = open;
  }}
>
  <Collapsible.Trigger class="flex w-full items-center justify-center gap-2">
    {night}
    {#if !opened}
      <ChevronUpIcon class="h-4 w-4" />
    {:else}
      <ChevronDownIcon class="h-4 w-4" />
    {/if}
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

        appState.removeFiles(night);
      }}
    >
      <XIcon class="h-4 w-4" />
    </Button>
  </Collapsible.Trigger>
  <Collapsible.Content class="gap-0">
    {#each files.filter((file) => isShown(file)) as file (file.path)}
      <FileComponent {night} {file} {appState} />
    {/each}
  </Collapsible.Content>
</Collapsible.Root>
