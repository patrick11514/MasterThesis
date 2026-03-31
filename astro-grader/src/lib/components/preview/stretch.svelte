<script lang="ts">
  import { ChartColumnIcon, LinkIcon, RotateCcwIcon, UnlinkIcon } from '@lucide/svelte';
  import Button from '../ui/button/button.svelte';
  import { previewState } from './state.svelte';
  import Slider from './stretch-slider.svelte';

  let linked = $state(true);
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
  <Slider bind:linked bind:sliders={previewState.channels} />
</section>
