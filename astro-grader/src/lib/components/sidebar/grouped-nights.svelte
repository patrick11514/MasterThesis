<script lang="ts">
  import { FILE_BADGES } from '$/lib/files/types';
  import type { Nights } from '$/lib/types/Nights';
  import { Badge } from '../ui/badge';
  import * as Resizable from '../ui/resizable';

  type ExtractGrouped<Raw> = Raw extends { GroupedNights: infer T } ? T : never;

  type Props = {
    nights: ExtractGrouped<Nights>;
  };

  const { nights }: Props = $props();

  const fileCounts = (session: ExtractGrouped<Nights>[number]) => ({
    Light: session.lights.length,
    Dark: session.darks.length,
    Flat: session.flats.length,
    Bias: session.biases.length
  });
</script>

<Resizable.Pane defaultSize={20} class="flex flex-col items-center gap-2 p-2">
  <div class="flex w-full flex-col gap-1 rounded-lg border border-border bg-muted/30 p-3">
    <div class="text-sm font-medium uppercase tracking-wide text-muted-foreground">
      Grouped frames
    </div>
    <div class="text-lg font-semibold">{nights.length} session{nights.length === 1 ? '' : 's'}</div>
  </div>

  <div class="flex w-full flex-1 flex-col gap-2 overflow-y-auto">
    {#if nights.length === 0}
      <p class="text-center text-muted-foreground">No grouped sessions available.</p>
    {:else}
      {#each nights as session (session.uuid)}
        <div class="rounded-lg border border-border p-3">
          <div class="mb-2 flex items-center justify-between gap-2">
            <div class="font-medium">{session.fingerprint.name}</div>
            <div class="text-xs text-muted-foreground">{session.uuid}</div>
          </div>

          <div class="grid gap-1 text-sm text-muted-foreground">
            <div>
              Filter: <span class="text-foreground">{session.fingerprint.filter || 'n/a'}</span>
            </div>
            <div>
              Exposure: <span class="text-foreground">{session.fingerprint.exposure}</span>
            </div>
            <div>
              Gain: <span class="text-foreground">{session.fingerprint.gain}</span>
            </div>
            <div>
              Temperature: <span class="text-foreground">{session.fingerprint.temperature}</span>
            </div>
          </div>

          <div class="mt-3 flex flex-wrap gap-2">
            {#each Object.entries(fileCounts(session)) as [type, count] (type)}
              <Badge
                variant="outline"
                class={{
                  [FILE_BADGES[type]]: true,
                  'opacity-60': count === 0
                }}
              >
                {type}: {count}
              </Badge>
            {/each}
          </div>
        </div>
      {/each}
    {/if}
  </div>
</Resizable.Pane>