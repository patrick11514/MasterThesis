<script lang="ts">
  import { LinkIcon, UnlinkIcon } from '@lucide/svelte';
  import Button from '../ui/button/button.svelte';
  import { previewState } from './state.svelte';
  import Slider from './stretch-slider.svelte';

  let linked = $state(true);
</script>

<section class="w-36">
  <Button size="icon-sm" variant="outline" onclick={() => (linked = !linked)}>
    {#if linked}
      <LinkIcon />
    {:else}
      <UnlinkIcon />
    {/if}
  </Button>
  <Slider
    bind:linked
    bind:shadows={previewState.shadows}
    bind:midtones={previewState.midtones}
    bind:highlights={previewState.highlights}
  />
  <pre>
  {JSON.stringify(previewState.previewData, null, 2)}
  </pre>
</section>
