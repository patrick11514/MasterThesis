<script lang="ts">
  import { CircleCheckBig, CircleX, LoaderIcon } from '@lucide/svelte';
  import type { FileBatchOperationProgressMessage } from '../types/FileBatchOperationProgressMessage';
  import { Badge } from './ui/badge';
  import { Button } from './ui/button';

  let {
    progress = null,
    onDone
  }: {
    progress: FileBatchOperationProgressMessage | null;
    onDone: () => void;
  } = $props();

  const operationLabel = (operation: FileBatchOperationProgressMessage['operation']) => {
    switch (operation) {
      case 'Move':
        return 'Moving files';
      case 'Delete':
        return 'Deleting files';
    }
  };

  const statusLabel = (status: FileBatchOperationProgressMessage['status']) => {
    switch (status) {
      case 'Running':
        return 'Running';
      case 'Completed':
        return 'Completed';
      case 'Failed':
        return 'Failed';
    }
  };

  const statusVariant = (status: FileBatchOperationProgressMessage['status']) => {
    switch (status) {
      case 'Running':
        return 'secondary' as const;
      case 'Completed':
        return 'default' as const;
      case 'Failed':
        return 'destructive' as const;
    }
  };

  const percent = $derived.by(() => {
    if (!progress || progress.total_count === 0) {
      return 0;
    }

    return Math.min(100, Math.round((progress.processed_count / progress.total_count) * 100));
  });
</script>

{#if progress}
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
    <div
      class="w-full max-w-2xl overflow-hidden rounded-2xl border border-border bg-background/95 shadow-2xl"
    >
      <div class="border-b border-border px-5 py-4">
        <div class="flex items-start justify-between gap-4">
          <div class="space-y-1">
            <div class="flex items-center gap-2 text-lg font-semibold tracking-tight">
              {#if progress.status === 'Running'}
                <LoaderIcon class="size-5 animate-spin text-primary" />
              {:else if progress.status === 'Completed'}
                <CircleCheckBig class="size-5 text-green-600 dark:text-green-400" />
              {:else}
                <CircleX class="size-5 text-destructive" />
              {/if}
              {operationLabel(progress.operation)}
            </div>
            <div class="text-sm text-muted-foreground">
              {progress.current_path ?? 'Preparing operation...'}
            </div>
          </div>

          <Badge variant={statusVariant(progress.status)}>{statusLabel(progress.status)}</Badge>
        </div>
      </div>

      <div class="space-y-4 px-5 py-5">
        <div class="flex items-center justify-between gap-3 text-sm text-muted-foreground">
          <span>{progress.processed_count} / {progress.total_count} files</span>
          <span>{percent}%</span>
        </div>

        <div class="h-2 overflow-hidden rounded-full bg-muted">
          <div
            class="h-full rounded-full bg-primary transition-all duration-200"
            style={`width: ${percent}%`}
          ></div>
        </div>

        {#if progress.error}
          <div
            class="rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {progress.error}
          </div>
        {/if}

        <div class="flex justify-end gap-2">
          {#if progress.status !== 'Running'}
            <Button onclick={onDone}>Done</Button>
          {/if}
        </div>
      </div>
    </div>
  </div>
{/if}
