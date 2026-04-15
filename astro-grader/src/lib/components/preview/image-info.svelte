<script lang="ts">
  import { ArrowLeftRightIcon } from '@lucide/svelte';
  import Button from '../ui/button/button.svelte';
  import * as DropdownMenu from '../ui/dropdown-menu';
  import { previewState } from './state.svelte';
  import Stretch from './stretch.svelte';

  //https://en.wikipedia.org/wiki/Bayer_filter
  const bayerPatterns = ['None', 'RGGB', 'BGGR', 'RGBG', 'GRBG'];
  const scalings = ['100%', '50%', '25%'];

  // We need to compare each key, and take these applied
  const currentOptions = $derived.by(() => {
    if (!previewState.previewData) {
      return null; // null ->
    }

    if (!previewState.imageOptions) {
      return previewState.previewData.applied_options; // -> applied
    }

    //compare keys, and select set of applied one

    const currentOptions = { ...previewState.imageOptions };
    const options = Object.keys(previewState.imageOptions) as (keyof typeof currentOptions)[];
    options.forEach((key) => {
      if (!currentOptions[key]) {
        //@ts-expect-error Here typescript doesn't know, if the key is missing, or the value is undefined, but in our case, it will be undefined
        currentOptions[key] = previewState.previewData?.applied_options?.[key] ?? undefined;
      }
    });

    return currentOptions;
  });

  // 1. Adapter for Bayer Pattern
  const getBayer = () => currentOptions?.bayer_pattern ?? 'None';
  const setBayer = (pattern: string) => {
    // @ts-expect-error TODO
    previewState.imageOptions = {
      ...currentOptions,
      bayer_pattern: pattern === 'None' ? null : pattern
    };
  };

  // 2. Adapter for Scaling
  const getScale = () => `${(currentOptions?.scale ?? 1) * 100}%`;
  const setScale = (value: string) => {
    // @ts-expect-error TODO
    previewState.imageOptions = {
      ...currentOptions,
      scale: parseInt(value, 10) / 100
    };
  };
</script>

{#if previewState.previewData}
  <div
    class="flex w-full flex-1 flex-col items-stretch justify-stretch divide-y divide-muted-foreground p-1"
  >
    <div class="flex flex-col items-center gap-1 py-2">
      <h2 class="text-xl font-semibold">Image Info</h2>
      <div class="flex flex-col gap-1 font-light">
        <div class="flex items-center gap-2">
          <span class="font-semibold">Dimensions:</span>
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
                <DropdownMenu.Label>Scaling</DropdownMenu.Label>
                <DropdownMenu.Separator />
                <DropdownMenu.RadioGroup bind:value={getScale, setScale}>
                  {#each scalings as scaling (scaling)}
                    <DropdownMenu.RadioItem value={scaling}>{scaling}</DropdownMenu.RadioItem>
                  {/each}
                </DropdownMenu.RadioGroup>
              </DropdownMenu.Group>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </div>
        <div class="flex items-center gap-2">
          <span class="font-semibold">Bayer Pattern:</span>
          {getBayer()}
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
                <DropdownMenu.RadioGroup bind:value={getBayer, setBayer}>
                  {#each bayerPatterns as pattern (pattern)}
                    <DropdownMenu.RadioItem value={pattern}>{pattern}</DropdownMenu.RadioItem>
                  {/each}
                </DropdownMenu.RadioGroup>
              </DropdownMenu.Group>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </div>
        <div class="flex items-center gap-2">
          <span class="font-semibold">Data type:</span>
          <span>{previewState.previewData.layout}</span>
        </div>
      </div>
    </div>
    <div class="flex flex-col items-center gap-1 py-2">
      <h2 class="text-xl font-semibold">Stretch</h2>
      <Stretch />
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
