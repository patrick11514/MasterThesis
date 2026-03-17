<script lang="ts">
  import * as Sidebar from '$/lib/components/ui/sidebar';
  import { Folder, FolderPlus, Plus } from '@lucide/svelte';
  import { toast } from 'svelte-sonner';
  import { promptDirectory, promptFiles } from '../files/utils';
  import { appState } from '../state.svelte';
  import { Button } from './ui/button';

  enum State {
    Idle,
    Scanning,
    Finished
  }

  let currentState = $state(State.Idle);

  const selectFiles = async (directory: boolean) => {
    currentState = State.Scanning;

    const files = directory ? await promptDirectory() : await promptFiles();

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
        <div class="flex w-full items-center justify-center gap-2">
          {#if currentState === State.Idle}
            <Folder class="h-4 w-4" /> Import files
          {:else if currentState === State.Scanning}
            Scanning for files...
          {:else if currentState === State.Finished}
            Done! You can add more files if you want.
          {/if}
        </div>
        <div class="flex gap-2">
          <Button
            disabled={currentState === State.Scanning}
            onclick={() => selectFiles(false)}
            variant="outline"
            size="sm"
          >
            <Plus class="h-4 w-4" /> Add new files
          </Button>
          <Button
            disabled={currentState === State.Scanning}
            onclick={() => selectFiles(true)}
            variant="outline"
            size="sm"
          >
            <FolderPlus class="h-4 w-4" />
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
