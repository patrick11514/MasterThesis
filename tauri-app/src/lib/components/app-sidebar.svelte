<script lang="ts">
  import * as Sidebar from '$/lib/components/ui/sidebar';
  import { FolderIcon, FolderPlusIcon, PlusIcon, SearchIcon } from '@lucide/svelte';
  import { Channel } from '@tauri-apps/api/core';
  import { tick } from 'svelte';
  import { toast } from 'svelte-sonner';
  import type { File } from '../files/types';
  import { promptDirectory, promptFiles } from '../files/utils';
  import { appState } from '../state.svelte';
  import { Button } from './ui/button';

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

    const prev = appState.files.length;
    appState.files = [...appState.files, ...(files ?? [])];
    const added = appState.files.length - prev;

    toast.success(`Added ${added} file${added !== 1 ? 's' : ''}!`);

    currentState = State.Finished;
  };
</script>

<Sidebar.Root>
  <Sidebar.Header>
    <Sidebar.Menu>
      <Sidebar.MenuItem class="flex flex-col items-center justify-center gap-2">
        <div class="flex w-full items-center justify-center gap-2 text-center text-sm">
          {#if currentState === State.Idle}
            <FolderIcon class="h-4 w-4" /> Import files
          {:else if currentState === State.Scanning}
            <SearchIcon class="h-4 w-4" /> Scanning... {scannedFiles} found
          {:else if currentState === State.Finished}
            <FolderIcon class="h-4 w-4" /> Done!
          {/if}
        </div>
        <div class="flex gap-2">
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
      </Sidebar.MenuItem>
    </Sidebar.Menu>
  </Sidebar.Header>
  <Sidebar.Content>
    <Sidebar.Group />
    <Sidebar.Group />
  </Sidebar.Content>
  <Sidebar.Footer />
</Sidebar.Root>
