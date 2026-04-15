<script lang="ts">
  import { FILE_BADGES } from '$/lib/files/types';
  import { getAppState } from '$/lib/state.svelte';
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

          <Badge variant="outline" class={FILE_BADGES.Dark}>
            Dark: {selectedSession.darks.length}
          </Badge>
          <Badge variant="outline" class={FILE_BADGES.Flat}>
            Flat: {selectedSession.flats.length}
          </Badge>
          <Badge variant="outline" class={FILE_BADGES.Bias}>
            Bias: {selectedSession.biases.length}
          </Badge>
        </div>
      {/if}
    </div>
  </ScrollArea>
</div>
