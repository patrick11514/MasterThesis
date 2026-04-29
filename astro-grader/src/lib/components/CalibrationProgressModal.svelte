<script lang="ts">
  import {
    Ban,
    ChevronDown,
    CircleCheckBig,
    CircleX,
    Clock3,
    LoaderIcon,
    TimerReset
  } from '@lucide/svelte';
  import type { CalibrationProgressMessage } from '../types/CalibrationProgressMessage';
  import type { CalibrationProgressStep } from '../types/CalibrationProgressStep';
  import { Badge } from './ui/badge';
  import { Button } from './ui/button';
  import * as Collapsible from './ui/collapsible';

  let {
    progress = null,
    onCancel,
    onDone
  }: {
    progress: CalibrationProgressMessage | null;
    onCancel: () => void;
    onDone?: () => void;
  } = $props();

  let now = $state(Date.now());
  let expandedSteps = $state<Record<string, boolean>>({});

  $effect(() => {
    if (!progress) {
      now = Date.now();
      return;
    }

    now = Date.now();
    const timer = window.setInterval(() => {
      now = Date.now();
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  });

  const toNumber = (value: number | bigint | null | undefined) => {
    if (typeof value === 'bigint') {
      return Number(value);
    }

    return value ?? 0;
  };

  const formatDuration = (
    startedAt: number | bigint | null | undefined,
    endedAt?: number | bigint | null
  ) => {
    if (!startedAt) {
      return '0:00';
    }

    const elapsed = Math.max(0, toNumber(endedAt ?? now) - toNumber(startedAt));
    const totalSeconds = Math.floor(elapsed / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }

    return `${minutes}:${String(seconds).padStart(2, '0')}`;
  };

  const overallElapsed = $derived(
    progress ? formatDuration(progress.started_at, progress.finished_at) : '0:00'
  );

  const overallStatusLabel = (status: CalibrationProgressMessage['status']) => {
    switch (status) {
      case 'Running':
        return 'Running';
      case 'Completed':
        return 'Completed';
      case 'Failed':
        return 'Failed';
      case 'Cancelled':
        return 'Cancelled';
    }
  };

  const stepStatusIcon = (step: CalibrationProgressStep) => {
    switch (step.status) {
      case 'Pending':
        return Clock3;
      case 'Running':
        return LoaderIcon;
      case 'Completed':
        return CircleCheckBig;
      case 'Failed':
      case 'Cancelled':
        return CircleX;
    }
  };

  const stepStatusBadge = (step: CalibrationProgressStep) => {
    switch (step.status) {
      case 'Pending':
        return 'outline';
      case 'Running':
        return 'secondary';
      case 'Completed':
        return 'default';
      case 'Failed':
        return 'destructive';
      case 'Cancelled':
        return 'ghost';
    }
  };

  const stepStatusLabel = (step: CalibrationProgressStep) => {
    switch (step.status) {
      case 'Pending':
        return 'Pending';
      case 'Running':
        return 'Running';
      case 'Completed':
        return 'Done';
      case 'Failed':
        return 'Failed';
      case 'Cancelled':
        return 'Cancelled';
    }
  };

  const stepIsActive = (step: CalibrationProgressStep) => step.status === 'Running';
  const canCancel = $derived(progress?.status === 'Running');
  const isCompleted = $derived(
    progress?.status === 'Completed' ||
      progress?.status === 'Failed' ||
      progress?.status === 'Cancelled'
  );

  const toggleStepExpanded = (stepId: string) => {
    expandedSteps[stepId] = !expandedSteps[stepId];
  };

  const handleActionClick = () => {
    if (canCancel) {
      onCancel();
    } else {
      onDone?.();
    }
  };

  const getElapsedLabel = (status: CalibrationProgressMessage['status']) => {
    return status === 'Running' ? 'Elapsed' : 'Finished in';
  };
</script>

{#if progress}
  <div
    class="fixed inset-0 z-50 flex items-end justify-start bg-black/60 p-4 backdrop-blur-sm sm:items-center sm:justify-center"
  >
    <div
      class="flex w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-border bg-background/95 shadow-2xl"
    >
      <div class="border-b border-border px-5 py-4">
        <div class="flex items-start justify-between gap-4">
          <div class="space-y-1">
            <div class="flex items-center gap-2 text-lg font-semibold tracking-tight">
              {#if progress.status === 'Running'}
                <LoaderIcon class="size-5 animate-spin text-primary" />
              {:else if progress.status === 'Completed'}
                <CircleCheckBig class="size-5 text-green-600 dark:text-green-400" />
              {:else if progress.status === 'Failed'}
                <CircleX class="size-5 text-destructive" />
              {:else}
                <Ban class="size-5 text-muted-foreground" />
              {/if}
              {progress.status === 'Running' ? 'Calibration in progress' : 'Calibration completed'}
            </div>
          </div>

          <Badge
            variant={progress.status === 'Running'
              ? 'secondary'
              : progress.status === 'Completed'
                ? 'default'
                : progress.status === 'Failed'
                  ? 'destructive'
                  : 'outline'}
          >
            {overallStatusLabel(progress.status)}
          </Badge>
        </div>
      </div>

      <div class="max-h-[60vh] overflow-y-auto px-5 py-4">
        <div class="space-y-2">
          {#each progress.steps as step (step.id)}
            {@const StepIcon = stepStatusIcon(step)}
            {@const isExpanded = expandedSteps[step.id] ?? false}
            <Collapsible.Root open={isExpanded}>
              <div
                role="button"
                tabindex="0"
                onclick={() => toggleStepExpanded(step.id)}
                onkeydown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    toggleStepExpanded(step.id);
                  }
                }}
                class={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors hover:border-primary/40 ${stepIsActive(step) ? 'border-primary/40 bg-primary/5' : 'border-border bg-muted/20'}`}
              >
                <div class="mt-0.5 flex shrink-0 items-center justify-center rounded-full">
                  <StepIcon class={`size-4 ${step.status === 'Running' ? 'animate-spin' : ''}`} />
                </div>

                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <div class="min-w-0">
                      <div class="truncate text-sm font-medium text-foreground">
                        {step.label}
                        {#if step.status === 'Running' || step.status === 'Completed'}
                          <span class="text-muted-foreground">
                            ({step.completed_count}/{step.count})
                          </span>
                        {:else}
                          <span class="text-muted-foreground">({step.count})</span>
                        {/if}
                      </div>
                    </div>

                    <div class="ml-auto flex items-center gap-2">
                      <Badge variant={stepStatusBadge(step)} class="shrink-0">
                        {stepStatusLabel(step)}
                      </Badge>
                      <span
                        class="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground tabular-nums"
                      >
                        <TimerReset class="size-3.5" />
                        {step.started_at ? formatDuration(step.started_at, step.ended_at) : '0:00'}
                      </span>
                    </div>
                  </div>
                </div>

                {#if step.error || step.session_label}
                  <ChevronDown
                    class={`my-auto size-4 shrink-0 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
                  />
                {/if}
              </div>

              {#if step.error || step.session_label}
                <Collapsible.Content class="ml-4 border-l-2 border-muted px-3 pt-2 pb-3">
                  <div class="space-y-2 text-xs">
                    {#if step.session_label}
                      <div class="text-muted-foreground">
                        <span class="font-medium">Session:</span>
                        {step.session_label}
                      </div>
                    {/if}
                    {#if step.error}
                      <div
                        class="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-destructive"
                      >
                        {step.error}
                      </div>
                    {/if}
                  </div>
                </Collapsible.Content>
              {/if}
            </Collapsible.Root>
          {/each}
        </div>
      </div>

      <div class="flex items-center justify-between gap-4 border-t border-border px-5 py-4">
        <div class="flex items-center gap-2 text-sm text-muted-foreground tabular-nums">
          <Clock3 class="size-4" />
          <span>{getElapsedLabel(progress.status)} {overallElapsed}</span>
        </div>

        <Button
          variant={canCancel ? 'destructive' : 'default'}
          size="sm"
          onclick={handleActionClick}
        >
          {#if canCancel}
            <Ban class="size-4" />
            Cancel
          {:else}
            <CircleCheckBig class="size-4" />
            Done
          {/if}
        </Button>
      </div>
    </div>
  </div>
{/if}
