<script lang="ts">
  import {
    ChevronUpIcon,
    FolderIcon,
    FolderPlusIcon,
    PlusIcon,
    SearchIcon,
    SettingsIcon,
    XIcon
  } from '@lucide/svelte';
  import { Channel } from '@tauri-apps/api/core';
  import { tick } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { promptDirectory, promptFiles } from '../files';
  import type { File } from '../files/types';
  import { getAppState } from '../state.svelte';
  import { Button, buttonVariants } from './ui/button';
  import * as Collapsible from './ui/collapsible';
  import * as Dialog from './ui/dialog';
  import { Input } from './ui/input';
  import * as Item from './ui/item';
  import { Label } from './ui/label';
  import ModeButton from './ui/mode-button.svelte';
  import * as Resizable from './ui/resizable';
  import { Switch } from './ui/switch';

  enum State {
    Idle,
    Scanning,
    Finished
  }

  let currentState = $state(State.Idle);
  let scannedFiles = $state(0);

  const selectFiles = async (directory: boolean) => {
    currentState = State.Scanning;

    let files: File[] | undefined;

    if (!directory) {
      files = await promptFiles();
      currentState = State.Scanning;
      await tick();
      currentState = State.Finished;
    } else {
      const channel = new Channel<number>();
      channel.onmessage = (message) => {
        scannedFiles = message;
      };

      files = await promptDirectory(channel);
    }

    if (!files) {
      currentState = State.Idle;
      return;
    }

    const added = appState.storeFiles(files);

    toast.success(`Added ${added} file${added !== 1 ? 's' : ''}!`);

    currentState = State.Finished;
  };

  const appState = await getAppState();

  const onNightConfigChange = async () => {
    await appState.saveConfig();

    appState.reApplyFilters();
  };
</script>

<Resizable.Pane defaultSize={20} class="flex flex-col items-center gap-2 p-2">
  <div class="flex w-full flex-col items-center justify-center gap-2">
    <div class="flex w-full flex-wrap items-center text-center text-lg">
      <ModeButton class="mr-auto" />
      <span class="mr-auto flex flex-wrap items-center gap-2">
        {#if currentState === State.Idle}
          <FolderIcon class="h-4 w-4" /> Import files
        {:else if currentState === State.Scanning}
          <SearchIcon class="h-4 w-4" /> Scanning... {scannedFiles} found
        {:else if currentState === State.Finished}
          <FolderIcon class="h-4 w-4" /> Done!
        {/if}
      </span>
      <ModeButton class="invisible" />
    </div>
    <div class="flex flex-wrap gap-2">
      <Button
        disabled={currentState === State.Scanning}
        onclick={() => selectFiles(false)}
        variant="outline"
        size="sm"
      >
        <PlusIcon class="h-4 w-4" /> Add new files
      </Button>
      <Button
        disabled={currentState === State.Scanning}
        onclick={() => selectFiles(true)}
        variant="outline"
        size="sm"
      >
        <FolderPlusIcon class="h-4 w-4" />
      </Button>
    </div>
  </div>
  <h2 class="text-lg">
    Night list
    <Dialog.Root>
      <Dialog.Trigger>
        <Button variant="outline" size="sm">
          <SettingsIcon class="h-4 w-4" />
        </Button>
      </Dialog.Trigger>
      <Dialog.Content>
        <Dialog.Header>
          <Dialog.Title>Night Settings</Dialog.Title>
          <Dialog.Description>
            Configure how the app identifies nights based on the file path. For example if you have
            files named like <code>Night_2024-01-01/file.fits</code>, you can set the prefix to
            <code>Night_</code>
            and then the nights will be idetified as <code>2024-01-01</code>.
          </Dialog.Description>
          <Button
            variant="default"
            size="sm"
            onclick={() => {
              appState.nightPrefixes.push({
                text: '',
                type: 'Prefix'
              });
            }}>Add Night Filter</Button
          >
          <div class="grid gap-4">
            {#each appState.nightPrefixes as filter, index (index)}
              <div class="flex items-center gap-2">
                <Input placeholder="Filter text" bind:value={filter.text} class="flex-1" />

                <Label>Prefix</Label>
                <Switch
                  bind:checked={
                    () => filter.type === 'Suffix', (v) => (filter.type = v ? 'Suffix' : 'Prefix')
                  }
                />
                <Label>Suffix</Label>

                <XIcon
                  class="h-4 w-4 cursor-pointer text-red-500"
                  onclick={() => {
                    appState.nightPrefixes.splice(index, 1);
                  }}
                />
              </div>
            {/each}
          </div>
          <Dialog.Footer>
            <Dialog.Close
              type="button"
              class={buttonVariants({ variant: 'outline' })}
              onclick={onNightConfigChange}
            >
              Close
            </Dialog.Close>
          </Dialog.Footer>
        </Dialog.Header>
      </Dialog.Content>
    </Dialog.Root>
  </h2>
  <div class="flex w-full flex-col gap-2 overflow-y-auto">
    {#if Object.keys(appState.files).length === 0}
      <p class="text-muted-foreground">No files imported.</p>
    {:else}
      {#each Object.entries(appState.files) as [night, files] (night)}
        <Collapsible.Root>
          <Collapsible.Trigger class="flex w-full items-center justify-center gap-2">
            {night}
            <ChevronUpIcon class="h-4 w-4" />
          </Collapsible.Trigger>
          <Collapsible.Content>
            {#each files as file (file.path)}
              <Item.Root>
                <Item.Content>
                  {file.name}
                </Item.Content>
                <Item.Footer class="text-sm text-muted-foreground">
                  {file.path}
                </Item.Footer>
              </Item.Root>
            {/each}
          </Collapsible.Content>
        </Collapsible.Root>
      {/each}
    {/if}
  </div>
</Resizable.Pane>
