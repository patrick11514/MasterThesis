<script lang="ts">
  import { ChartColumnIcon, LinkIcon, RotateCcwIcon, UnlinkIcon } from '@lucide/svelte';
  import Button from '../ui/button/button.svelte';
  import { PreserveRatio, type SMH } from './preserve-ratio.svelte';
  import { previewState } from './state.svelte';
  import Slider from './stretch-slider.svelte';

  let linked = $state(true);

  const channels = $derived.by(() => {
    if (!previewState.previewData) return [];

    if (previewState.previewData.layout === 'Grayscale') {
      return [
        {
          id: 'G',
          value: previewState.R,
          color: 'gray',
          ratios: new PreserveRatio(previewState.R)
        }
      ];
    }

    const colors = {
      R: 'red',
      G: 'green',
      B: 'blue'
    } as const;

    return ['R', 'G', 'B'].map((_c: string) => {
      {
        const c = _c as 'R' | 'G' | 'B';
        return {
          id: c,
          value: previewState[c],
          color: colors[c],
          ratios: new PreserveRatio(previewState[c])
        };
      }
    });
  });

  const onChange = (channels: SMH[]) => {
    if (channels.length === 0) return;
    if (channels.length === 1) {
      const v = channels[0];
      previewState.R = v;
      previewState.G = v;
      previewState.B = v;
    } else {
      const [r, g, b] = channels;
      previewState.R = r;
      previewState.G = g;
      previewState.B = b;
    }
  };
</script>

<section class="w-full p-1">
  <Button size="icon-sm" variant="outline" onclick={() => (linked = !linked)}>
    {#if linked}
      <LinkIcon />
    {:else}
      <UnlinkIcon />
    {/if}
  </Button>
  <Button
    size="icon-sm"
    variant="outline"
    onclick={() => {
      previewState.R = [0, 0.5, 1];
      previewState.G = [0, 0.5, 1];
      previewState.B = [0, 0.5, 1];
    }}
  >
    <RotateCcwIcon />
  </Button>
  <Button
    size="icon-sm"
    variant="outline"
    onclick={() => {
      if (!previewState.previewData) return;
      if (!previewState.previewData.auto_stf) return;

      console.log(
        'APplying STF',
        linked ? 'linked' : 'unlinked',
        previewState.previewData.auto_stf
      );

      let stf = linked
        ? previewState.previewData.auto_stf.linked
        : previewState.previewData.auto_stf.unlinked;

      previewState.R = stf.r;
      previewState.G = stf.g;
      previewState.B = stf.b;

      console.log('Applied');
    }}
  >
    <ChartColumnIcon />
  </Button>
  <Slider bind:linked {channels} {onChange} />
</section>
