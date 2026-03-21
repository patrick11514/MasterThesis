<script lang="ts">
  import { FolderIcon, FolderPlusIcon, PlusIcon, SearchIcon } from '@lucide/svelte';
  import { Channel } from '@tauri-apps/api/core';
  import { tick } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { promptDirectory, promptFiles } from '../../files';
  import { getAppState } from '../../state.svelte';
  import type { File } from '../../types/File';
  import { Button } from '../ui/button';
  import ModeButton from '../ui/mode-button.svelte';

  enum State {
    Idle,
    Scanning,
    Finished
  }

  let currentState = $state(State.Idle);
  let scannedFiles = $state(0);

  const appState = await getAppState();

  const selectFiles = async (directory: boolean) => {
    currentState = State.Scanning;
    scannedFiles = 0;

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
</script>

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
