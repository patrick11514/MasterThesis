<script lang="ts">
  import { FILE_BADGES } from '$/lib/files/types';
  import { getAppState } from '$/lib/state.svelte';
  import type { MasterOrFrames } from '$lib/types/MasterOrFrames';
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

  function countMasterOrFrames(frames: MasterOrFrames): number {
    return 'Frames' in frames ? frames.Frames.length : 1;
  }
</script>

<div class="flex h-full w-full flex-col gap-2 border-t border-border bg-muted/20 p-3">
  <div class="text-sm font-medium tracking-wide text-muted-foreground uppercase">
    Grouped sessions
  </div>

  <ScrollArea orientation="horizontal" class="w-full">
    <div class="flex w-max gap-2">
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

        <div class="mt-3 overflow-x-auto rounded-md border border-border bg-background/60">
          <table class="w-full min-w-140 text-sm">
            <thead
              class="bg-muted/40 text-left text-xs tracking-wide text-muted-foreground uppercase"
            >
              <tr>
                <th class="px-3 py-2 font-medium">Filename</th>
                <th class="px-3 py-2 font-medium">Star count</th>
                <th class="px-3 py-2 font-medium">FWHM</th>
                <th class="px-3 py-2 font-medium">Background contrast</th>
              </tr>
            </thead>
            <tbody>
              {#if selectedSession.lights.length === 0}
                <tr class="border-t border-border/70">
                  <td colspan={4} class="px-3 py-3 text-muted-foreground">
                    No light frames in this grouped session.
                  </td>
                </tr>
              {:else}
                {#each selectedSession.lights as light (light.path)}
                  <tr class="border-t border-border/70">
                    <td class="max-w-[320px] truncate px-3 py-2 text-foreground" title={light.name}>
                      {light.name}
                    </td>
                    <td class="px-3 py-2 text-muted-foreground">
                      {light.stats?.star_count ?? '-'}
                    </td>
                    <td class="px-3 py-2 text-muted-foreground">
                      {formatMetric(light.stats?.fwhm)}
                    </td>
                    <td class="px-3 py-2 text-muted-foreground">
                      {formatMetric(light.stats?.background_contrast, 3)}
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
