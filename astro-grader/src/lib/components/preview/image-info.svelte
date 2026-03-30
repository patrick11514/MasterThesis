<script lang="ts">
  import { ArrowLeftRightIcon } from '@lucide/svelte';
  import Button from '../ui/button/button.svelte';
  import * as DropdownMenu from '../ui/dropdown-menu';
  import { previewState } from './state.svelte';
  import Stretch from './stretch.svelte';

  //https://en.wikipedia.org/wiki/Bayer_filter
  const bayerPatterns = ['None', 'RGGB', 'BGGR', 'RGBG', 'GRBG'];
  const scalings = ['100%', '50%', '25%'];

  let currentBayerPattern = $derived(
    previewState.previewData?.applied_options.bayer_pattern ?? 'None'
  );

  $effect(() => {
    console.log(currentBayerPattern);
  });

  let scaling = $derived(`${(previewState.previewData?.applied_options.scale ?? 1) * 100}%`);

  $effect(() => {
    console.log(scaling);
  });
</script>

{#if previewState.previewData}
  <div
    class="flex w-full flex-1 flex-col items-stretch justify-stretch divide-y divide-muted-foreground p-1"
  >
    <div class="flex flex-col items-center gap-1 py-2">
      <h2 class="text-xl font-semibold">Image Info</h2>
      <div class="flex flex-col gap-1">
        <div class="flex items-center gap-2">
          <span class="font-semibold">Dimensions:</span>
          <span>
            {previewState.previewData.width} x {previewState.previewData.height}
            <DropdownMenu.Root>
              <DropdownMenu.Trigger>
                {#snippet child({ props })}
                  <Button {...props} variant="outline" size="icon-sm">
                    <ArrowLeftRightIcon />
                  </Button>
                {/snippet}
              </DropdownMenu.Trigger>
              <DropdownMenu.Content class="w-56">
                <DropdownMenu.Group>
                  <DropdownMenu.Label>Bayer Pattern</DropdownMenu.Label>
                  <DropdownMenu.Separator />
                  <DropdownMenu.RadioGroup
                    bind:value={
                      () => currentBayerPattern,
                      (pattern) => {
                        previewState.imageOptions = {
                          ...previewState.imageOptions,
                          bayer_pattern: pattern === 'None' ? null : pattern
                        };
                      }
                    }
                  >
                    {#each bayerPatterns as pattern (pattern)}
                      <DropdownMenu.RadioItem value={pattern}>{pattern}</DropdownMenu.RadioItem>
                    {/each}
                  </DropdownMenu.RadioGroup>
                </DropdownMenu.Group>
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          </span>
        </div>
        <div class="flex items-center gap-2">
          <span class="font-semibold">Bayer Pattern:</span>
          <span>
            {currentBayerPattern}
            <DropdownMenu.Root>
              <DropdownMenu.Trigger>
                {#snippet child({ props })}
                  <Button {...props} variant="outline" size="icon-sm">
                    <ArrowLeftRightIcon />
                  </Button>
                {/snippet}
              </DropdownMenu.Trigger>
              <DropdownMenu.Content class="w-56">
                <DropdownMenu.Group>
                  <DropdownMenu.Label>Scaling</DropdownMenu.Label>
                  <DropdownMenu.Separator />
                  <DropdownMenu.RadioGroup
                    bind:value={
                      () => scaling,
                      (value) => {
                        const scaleValue = parseInt(value) / 100;
                        previewState.imageOptions = {
                          ...previewState.imageOptions,
                          scale: scaleValue
                        };
                      }
                    }
                  >
                    {#each scalings as scaling (scaling)}
                      <DropdownMenu.RadioItem value={scaling}>{scaling}</DropdownMenu.RadioItem>
                    {/each}
                  </DropdownMenu.RadioGroup>
                </DropdownMenu.Group>
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          </span>
        </div>
        <div class="flex items-center gap-2">
          <span class="font-semibold">Data type:</span>
          <span>{previewState.previewData.layout}</span>
        </div>
      </div>
    </div>
    <div class="flex w-full flex-col gap-1 py-2">
      <h2>Stretch</h2>
      <Stretch />
    </div>
    <div class="flex w-full flex-col gap-1 py-2">
      <h2>Debug</h2>
      <pre>
        {JSON.stringify(previewState.previewData, null, 2)}
        {JSON.stringify({ R: previewState.R, G: previewState.G, B: previewState.B }, null, 2)}
       </pre>
    </div>
  </div>
{:else}
  <div class="flex flex-col items-center justify-center gap-2 p-4">
    <h2 class="text-lg font-semibold">No image loaded</h2>
    <p class="text-sm text-muted-foreground">
      Please select a FITS file from the sidebar to see its preview and information here.
    </p>
  </div>
{/if}
