<script lang="ts">
  import { previewState } from '$/lib/components/preview/state.svelte';
  import { FILE_BADGES } from '$/lib/files/types';
  import { getAppState } from '$/lib/state.svelte';
  import type { MasterOrFrames } from '$lib/types/MasterOrFrames';
  import { CheckIcon, XIcon } from '@lucide/svelte';
  import { toast } from 'svelte-sonner';
  import { Badge } from './ui/badge';
  import { Button } from './ui/button';
  import ScrollArea from './ui/scroll-area/scroll-area.svelte';

  const appState = await getAppState();

  const selectedSession = $derived.by(() => {
    if (appState.groupedNights.length === 0) {
      return null;
    }

    return (
      appState.groupedNights.find(
        (session) => session.uuid === appState.activeGroupedSessionUuid
      ) ?? appState.groupedNights[0]
    );
  });

  $effect(() => {
    if (!selectedSession) {
      return;
    }

    if (selectedSession.uuid !== appState.activeGroupedSessionUuid) {
      appState.setActiveGroupedSession(selectedSession.uuid);
    }
  });

  function formatMetric(value: number | null | undefined, decimals = 2): string {
    if (value === null || value === undefined) {
      return '-';
    }

    return value.toFixed(decimals);
  }

  // Selection map keyed by file path
  let selectionMap: Record<string, boolean> = {};

  function getSelectedCount() {
    return Object.values(selectionMap).filter(Boolean).length;
  }

  function isSelected(path: string) {
    return !!selectionMap[path];
  }

  function toggleSelect(path: string) {
    selectionMap[path] = !selectionMap[path];
    selectionMap = { ...selectionMap };
  }

  function clearSelection() {
    selectionMap = {};
  }

  function selectAllVisible(visiblePaths: string[]) {
    const allSelected = visiblePaths.every((p) => !!selectionMap[p]);
    if (allSelected) {
      for (const p of visiblePaths) {
        delete selectionMap[p];
      }
    } else {
      for (const p of visiblePaths) {
        selectionMap[p] = true;
      }
    }
    selectionMap = { ...selectionMap };
  }

  function selectAllRejected() {
    if (!selectedSession) return;
    for (const l of selectedSession.lights) {
      if (l.state === 'Rejected') selectionMap[l.path] = true;
    }
    selectionMap = { ...selectionMap };
  }

  async function moveSelected() {
    const paths = Object.keys(selectionMap).filter((p) => selectionMap[p]);
    if (paths.length === 0) return;
    // placeholder
    toast.info(`Move selected files: ${paths.length} (TODO)`);
  }

  async function removeSelected() {
    const paths = Object.keys(selectionMap).filter((p) => selectionMap[p]);
    if (paths.length === 0) return;
    const ok = confirm(`Remove ${paths.length} selected files from the project?`);
    if (!ok) return;

    for (const path of paths) {
      const entry = Object.entries(appState.rawNights).find(([, files]) =>
        files.some((f) => f.path === path)
      );
      const night = entry?.[0] ?? null;
      if (night) {
        appState.removeFiles(night, path);
      }
    }

    clearSelection();
    toast.success('Removed selected files');
  }

  function countMasterOrFrames(frames: MasterOrFrames): number {
    return 'Frames' in frames ? frames.Frames.length : 1;
  }

  function statusBadgeClass(state: string) {
    switch (state) {
      case 'Accepted':
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300';
      case 'Rejected':
        return 'border-destructive/30 bg-destructive/10 text-destructive';
      case 'Calibrated':
        return 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300';
      default:
        return 'border-border bg-background text-muted-foreground';
    }
  }
</script>

<div class="flex h-full w-full flex-col gap-2 border-t border-border bg-muted/20 p-3">
  <div class="text-sm font-medium tracking-wide text-muted-foreground uppercase">
    Grouped sessions
  </div>

  <ScrollArea orientation="horizontal" class="w-full">
    <div class="flex w-max gap-2 py-1">
      {#each appState.groupedNights as session (session.uuid)}
        <Button
          variant={session.uuid === appState.activeGroupedSessionUuid ? 'default' : 'outline'}
          size="sm"
          onclick={() => appState.setActiveGroupedSession(session.uuid)}
        >
          {session.fingerprint.name} / {session.fingerprint.filter || 'n/a'} / {session.fingerprint
            .exposure}s
        </Button>
      {/each}
    </div>
  </ScrollArea>

  <ScrollArea orientation="vertical" class="min-h-0">
    <div class="h-max w-full p-2">
      {#if selectedSession}
        <div class="grid gap-1 text-sm text-muted-foreground">
          <div>
            Name: <span class="text-foreground">{selectedSession.fingerprint.name}</span>
          </div>
          <div>
            Filter: <span class="text-foreground">
              {selectedSession.fingerprint.filter || 'n/a'}
            </span>
          </div>
          <div>
            Exposure: <span class="text-foreground">{selectedSession.fingerprint.exposure}</span>
          </div>
          <div>
            Gain: <span class="text-foreground">{selectedSession.fingerprint.gain}</span>
          </div>
          <div>
            Temperature: <span class="text-foreground">
              {selectedSession.fingerprint.temperature}
            </span>
          </div>
        </div>

        <div class="flex flex-wrap gap-2">
          <Badge variant="outline" class={FILE_BADGES.Light}>
            Light: {selectedSession.lights.length}
          </Badge>

          {#if 'Master' in selectedSession.darks}
            <Badge variant="outline" class={FILE_BADGES.Dark}>Master Dark found</Badge>
          {:else}
            <Badge variant="outline" class={FILE_BADGES.Dark}>
              Dark: {countMasterOrFrames(selectedSession.darks)}
            </Badge>
          {/if}

          {#if 'Master' in selectedSession.flats}
            <Badge variant="outline" class={FILE_BADGES.Flat}>Master Flat found</Badge>
          {:else}
            <Badge variant="outline" class={FILE_BADGES.Flat}>
              Flat: {countMasterOrFrames(selectedSession.flats)}
            </Badge>
          {/if}

          {#if 'Master' in selectedSession.biases}
            <Badge variant="outline" class={FILE_BADGES.Bias}>Master Bias found</Badge>
          {:else}
            <Badge variant="outline" class={FILE_BADGES.Bias}>
              Bias: {countMasterOrFrames(selectedSession.biases)}
            </Badge>
          {/if}
        </div>

        <div class="mt-3 flex items-center justify-between gap-2">
          <div class="flex gap-2">
            <Button size="sm" variant="outline" onclick={selectAllRejected}>
              Select all rejected
            </Button>
            <Button
              size="sm"
              variant="outline"
              onclick={moveSelected}
              disabled={getSelectedCount() === 0}
            >
              Move selected files
            </Button>
            <Button
              size="sm"
              variant="destructive"
              onclick={removeSelected}
              disabled={getSelectedCount() === 0}
            >
              Remove selected files
            </Button>
            <Button
              onclick={() => {
                for (const night in appState.rawNights) {
                  for (const file of appState.rawNights[night]) {
                    file.state = 'Default';
                    file.stats = null;
                  }
                }

                for (const session of appState.groupedNights) {
                  for (const light of session.lights) {
                    light.state = 'Default';
                    light.stats = null;
                  }
                }

                appState.persistFeState();
              }}
            >
              Reset metrics
            </Button>
          </div>
          <div class="text-sm text-muted-foreground">Selected: {getSelectedCount()}</div>
        </div>

        <h1 class="mt-2 text-xl font-bold">Light frames</h1>

        <div class="mt-3 overflow-x-auto rounded-md border border-border bg-background/60">
          <table class="w-full min-w-140 text-sm">
            <thead
              class="bg-muted/40 text-left text-xs tracking-wide text-muted-foreground uppercase"
            >
              <tr>
                <th class="px-3 py-2 font-medium">
                  <input
                    type="checkbox"
                    checked={getSelectedCount() === (selectedSession?.lights.length ?? 0) &&
                      (selectedSession?.lights.length ?? 0) > 0}
                    onclick={(e: any) => {
                      e.stopPropagation();
                      selectAllVisible(selectedSession?.lights.map((l) => l.path) ?? []);
                    }}
                  />
                </th>
                <th class="px-3 py-2 font-medium">Filename</th>
                <th class="px-3 py-2 font-medium">Calibrated</th>
                <th class="px-3 py-2 font-medium">Status</th>
                <th class="px-3 py-2 font-medium">Star count</th>
                <th class="px-3 py-2 font-medium">Eccentricity</th>
                <th class="px-3 py-2 font-medium">FWHM</th>
                <th class="px-3 py-2 font-medium">Background contrast</th>
                <th class="px-3 py-2 font-medium">Exposure (s)</th>
                <th class="px-3 py-2 font-medium">Gain</th>
                <th class="px-3 py-2 font-medium">Temperature (C)</th>
                <th class="px-3 py-2 font-medium">Quality</th>
              </tr>
            </thead>
            <tbody>
              {#if selectedSession.lights.length === 0}
                <tr class="border-t border-border/70">
                  <td colspan={10} class="px-3 py-3 text-muted-foreground">
                    No light frames in this grouped session.
                  </td>
                </tr>
              {:else}
                {#each selectedSession.lights as light (light.path)}
                  <tr class="border-t border-border/70">
                    <td class="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={isSelected(light.path)}
                        onclick={(e: any) => {
                          e.stopPropagation();
                          toggleSelect(light.path);
                        }}
                      />
                    </td>
                    <td
                      class="max-w-[320px] truncate px-3 py-2 text-foreground"
                      title={light.path}
                      onclick={(ev) => {
                        // prevent from clicking through when using buttons/checkbox
                        // @ts-expect-error
                        if (ev.target?.closest('button') || ev.target?.closest('input')) return;
                        previewState.previewImage = light;
                        previewState.imageOptions = undefined;
                        appState.setCurrentPreviewFile(light.path);
                      }}
                    >
                      {light.name}
                    </td>
                    <td>
                      {#if light.calibrated_frame}
                        <CheckIcon class="size-5 text-green-500" />
                      {:else}
                        <XIcon class="size-5 text-red-500" />
                      {/if}
                    </td>
                    <td class="px-3 py-2">
                      <Badge variant="outline" class={statusBadgeClass(light.state)}>
                        {light.state}
                      </Badge>
                    </td>
                    <td class="px-3 py-2 text-muted-foreground">
                      {light.stats?.star_count ?? '-'}
                    </td>
                    <td class="px-3 py-2 text-muted-foreground">
                      {formatMetric(light.stats?.eccentricity, 3)}
                    </td>
                    <td class="px-3 py-2 text-muted-foreground">
                      {formatMetric(light.stats?.fwhm)}
                    </td>
                    <td class="px-3 py-2 text-muted-foreground">
                      {formatMetric(light.stats?.background_contrast, 3)}
                    </td>
                    <td class="px-3 py-2 text-muted-foreground">
                      {formatMetric(light.default_headers?.exposure_time, 2)}
                    </td>
                    <td class="px-3 py-2 text-muted-foreground">
                      {formatMetric(light.default_headers?.gain, 2)}
                    </td>
                    <td class="px-3 py-2 text-muted-foreground">
                      {formatMetric(light.default_headers?.temperature, 1)}
                    </td>
                    <td class="px-3 py-2 text-muted-foreground">
                      {formatMetric(light.stats?.quality_score)}
                    </td>
                  </tr>
                {/each}
              {/if}
            </tbody>
          </table>
        </div>
      {/if}
    </div>
  </ScrollArea>
</div>
