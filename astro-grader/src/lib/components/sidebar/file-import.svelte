<script lang="ts">
  import { FolderPlusIcon, LoaderIcon, PlusIcon, SearchIcon, XIcon } from '@lucide/svelte';
  import { Channel } from '@tauri-apps/api/core';
  import { tick } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { cancelDirectoryScan, promptDirectory, promptFiles } from '../../files';
  import { getAppState } from '../../state.svelte';
  import type { File } from '../../types/File';
  import { Button } from '../ui/button';
  import ModeButton from '../ui/mode-button.svelte';

  enum State {
    Idle,
    Scanning,
    Grouping,
    Finished
  }

  let currentState: State = $state(State.Idle);
  let scannedFiles = $state(0);
  let cancelRequested = $state(false);
  let groupingProgress = $state({ processed: 0, total: 0 });

  const appState = await getAppState();

  const selectFiles = async (directory: boolean) => {
    currentState = State.Scanning;
    scannedFiles = 0;
    cancelRequested = false;

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

    if (cancelRequested) {
      toast.success(`Import canceled, added ${added} file${added !== 1 ? 's' : ''}.`);
    } else {
      toast.success(`Added ${added} file${added !== 1 ? 's' : ''}!`);
    }

    currentState = State.Finished;
    cancelRequested = false;
  };

  const cancelScan = async () => {
    cancelRequested = true;

    try {
      await cancelDirectoryScan();
    } catch (error) {
      cancelRequested = false;
      toast.error('Failed to cancel scanning', {
        description: error as string
      });
    }
  };

  const groupFrames = async () => {
    currentState = State.Grouping;
    groupingProgress = {
      processed: 0,
      total: Object.values(appState.rawNights).flat().length
    };

    const grouped = await appState.groupFrames((progress) => {
      groupingProgress = progress;
    });

    currentState = grouped ? State.Finished : State.Idle;
  };

  const groupPercent = $derived.by(() => {
    if (groupingProgress.total === 0) {
      return 0;
    }

    return Math.min(100, Math.round((groupingProgress.processed / groupingProgress.total) * 100));
  });

  const busy = $derived.by(
    () => currentState === State.Scanning || currentState === State.Grouping
  );
</script>

<div class="flex w-full flex-col items-center justify-center gap-2">
  <div class="flex w-full flex-wrap gap-2">
    <ModeButton class="mr-auto" />
    <Button disabled={busy} onclick={() => selectFiles(false)} variant="outline" size="sm">
      <PlusIcon class="h-4 w-4" /> Add new files
    </Button>
    <Button disabled={busy} onclick={() => selectFiles(true)} variant="outline" size="sm">
      <FolderPlusIcon class="h-4 w-4" />
    </Button>
    <ModeButton class="invisible ml-auto" />
  </div>

  {#if currentState === State.Scanning}
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
    >
      <div class="w-full max-w-sm rounded-xl border border-border bg-background p-5 shadow-2xl">
        <div class="mb-3 flex items-center gap-2 text-base font-medium">
          <SearchIcon class="h-4 w-4 animate-pulse" /> Scanning files
        </div>
        <div class="mb-2 flex items-center justify-between text-sm text-muted-foreground">
          <span>
            {cancelRequested ? 'Stopping scan...' : `Scanned ${scannedFiles} files`}
          </span>
        </div>
        <div class="flex justify-end gap-2">
          <Button variant="destructive" size="sm" onclick={cancelScan} disabled={cancelRequested}>
            <XIcon class="h-4 w-4" /> Stop
          </Button>
        </div>
      </div>
    </div>
  {/if}

  <div class="flex">
    {#if Object.keys(appState.rawNights).length > 0}
      <Button disabled={busy} onclick={groupFrames} variant="default" size="sm">
        <LoaderIcon class="h-4 w-4" /> Group frames
      </Button>
    {/if}
  </div>

  {#if currentState === State.Grouping}
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
    >
      <div class="w-full max-w-sm rounded-xl border border-border bg-background p-5 shadow-2xl">
        <div class="mb-3 flex items-center gap-2 text-base font-medium">
          <LoaderIcon class="h-4 w-4 animate-spin" /> Grouping frames
        </div>
        <div class="mb-2 flex items-center justify-between text-sm text-muted-foreground">
          <span>{groupingProgress.processed} / {groupingProgress.total} files</span>
          <span>{groupPercent}%</span>
        </div>
        <div class="h-2 overflow-hidden rounded-full bg-muted">
          <div
            class="h-full rounded-full bg-primary transition-all duration-200"
            style={`width: ${groupPercent}%`}
          ></div>
        </div>
      </div>
    </div>
  {/if}
</div>
