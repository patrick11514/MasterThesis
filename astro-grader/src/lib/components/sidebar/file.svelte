<script lang="ts">
  import { previewState } from '$/lib/components/preview/state.svelte';
  import { FILE_COLORS, FILE_TYPES } from '$/lib/files/types';
  import type { AppStateType } from '$/lib/state.svelte';
  import type { File } from '$/lib/types/File';
  import { ArrowLeftRightIcon, FileImageIcon, InfoIcon, XIcon } from '@lucide/svelte';
  import { Button } from '../ui/button';
  import * as DropdownMenu from '../ui/dropdown-menu';
  import * as Item from '../ui/item';
  import * as Popover from '../ui/popover';

  interface Props {
    night: string;
    file: File;
    appState: AppStateType;
  }
  const { night, file, appState }: Props = $props();

  const getType = () => file.type;
  const setType = (type: File['type']) => {
    appState.updateFileType(night, file.path, type);
  };
</script>

<Item.Root class="w-full border-none p-0">
  <Item.Content
    class="flex w-full flex-row items-center gap-2"
    onclick={(ev) => {
      //@ts-expect-error This hack prevents calling when using popover / remove button
      if (ev.target?.closest('button')) {
        return;
      }

      previewState.previewImage = file;
      previewState.imageOptions = undefined;
      appState.setCurrentPreviewFile(file.path);
    }}
  >
    <FileImageIcon class={FILE_COLORS[file.type]} />
    <span class="flex-1 truncate">{file.name}</span>
    {#if file.state === 'Accepted'}
      <span
        class="ml-2 inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800"
      >
        Accepted
      </span>
    {:else if file.state === 'Rejected'}
      <span
        class="ml-2 inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800"
        title={file.reject_reason ?? 'Rejected'}
        aria-label={file.reject_reason ?? 'Rejected'}
      >
        Rejected
      </span>
    {/if}

    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        {#snippet child({ props })}
          <Button {...props} variant="outline" size="icon-sm">
            <ArrowLeftRightIcon />
          </Button>
        {/snippet}
      </DropdownMenu.Trigger>
      <DropdownMenu.Content class="w-56">
        <DropdownMenu.Group>
          <DropdownMenu.Label>File Type</DropdownMenu.Label>
          <DropdownMenu.Separator />
          <DropdownMenu.RadioGroup bind:value={getType, setType}>
            {#each FILE_TYPES as type (type)}
              <DropdownMenu.RadioItem value={type}>{type}</DropdownMenu.RadioItem>
            {/each}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Group>
      </DropdownMenu.Content>
    </DropdownMenu.Root>
    <Popover.Root>
      <Popover.Trigger class="shrink-0">
        {#snippet child({ props })}
          <Button {...props} variant="outline" size="icon-sm">
            <InfoIcon />
          </Button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content class="flex w-max flex-col gap-2">
        <div>
          <strong>Name:</strong>
          {file.name}
        </div>
        <div>
          <strong>Path:</strong>
          {file.path}
        </div>
        <div>
          <strong>Type:</strong>
          {file.type}
        </div>
        {#if file.default_headers.temperature !== undefined}
          <div>
            <strong>Temperature:</strong>
            {file.default_headers.temperature}
          </div>
        {/if}
        {#if file.default_headers.exposure_time !== undefined}
          <div>
            <strong>Exposure Time:</strong>
            {file.default_headers.exposure_time}
          </div>
        {/if}
        {#if file.default_headers.gain !== undefined}
          <div>
            <strong>Gain:</strong>
            {file.default_headers.gain}
          </div>
        {/if}
      </Popover.Content>
    </Popover.Root>
    <Button
      class="shrink-0"
      variant="destructive"
      size="icon-sm"
      onclick={() => {
        appState.removeFiles(night, file.path);
      }}
    >
      <XIcon />
    </Button>
  </Item.Content>
</Item.Root>
