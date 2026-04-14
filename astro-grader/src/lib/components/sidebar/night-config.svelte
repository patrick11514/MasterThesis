<script lang="ts">
  import { getAppState } from '$/lib/state.svelte';
  import { InfoIcon, SettingsIcon, XIcon } from '@lucide/svelte';
  import { Button, buttonVariants } from '../ui/button';
  import * as Dialog from '../ui/dialog';
  import { Input } from '../ui/input';
  import { Label } from '../ui/label';
  import Separator from '../ui/separator/separator.svelte';
  import { Switch } from '../ui/switch';
  import * as Tooltip from '../ui/tooltip';

  const appState = await getAppState();
  let temperatureStepInput = $state<HTMLInputElement | null>(null);

  const helpCopy = {
    nightList: {
      title: 'Night list',
      description:
        'This section controls how nights are grouped in the sidebar and how the list is displayed.',
      example:
        'Example: keep related sessions together by tuning the temperature, exposure, and gain steps.'
    },
    groupingOffsets: {
      title: 'Grouping offsets',
      description:
        'Files whose temperature, exposure, or gain values stay within these offsets are grouped together.',
      example:
        'Example: 0.1 for temperature, 0.1 for exposure, and 10 for gain keeps near-matching captures in one night.'
    },
    nightNameParsing: {
      title: 'Night name parsing',
      description:
        'These filters tell the app which part of the filename should be treated as the night label.',
      example:
        'Example: Prefix=2026 with Match first enabled on /path/to/2026-24/2026-89.fit gives -24 and ignores later 2026 parts.'
    }
  };

  const onDialogOpenAutoFocus = (event: Event) => {
    event.preventDefault();
    temperatureStepInput?.focus();
  };

  const onNightConfigChange = async () => {
    await appState.saveConfig();

    appState.reApplyFilters();
  };
</script>

<h2 class="flex items-center gap-2 text-lg">
  <span>Night list</span>
  <Tooltip.Root>
    <Tooltip.Trigger>
      {#snippet child({ props })}
        <Button
          {...props}
          variant="ghost"
          size="icon-sm"
          class="shrink-0 text-muted-foreground hover:text-foreground"
          aria-label="Show Night list help"
        >
          <InfoIcon class="h-4 w-4" />
        </Button>
      {/snippet}
    </Tooltip.Trigger>
    <Tooltip.Content class="max-w-sm">
      <div class="grid gap-1.5">
        <strong>{helpCopy.nightList.title}</strong>
        <p>{helpCopy.nightList.description}</p>
        <p>{helpCopy.nightList.example}</p>
      </div>
    </Tooltip.Content>
  </Tooltip.Root>
  <Dialog.Root>
    <Dialog.Trigger>
      <Button variant="outline" size="sm">
        <SettingsIcon class="h-4 w-4" />
      </Button>
    </Dialog.Trigger>
    <Dialog.Content onOpenAutoFocus={onDialogOpenAutoFocus}>
      <Dialog.Header>
        <Dialog.Title>Night Settings</Dialog.Title>

        <h2 class="flex items-center gap-2 text-base font-medium">
          <span>Grouping offsets</span>
          <Tooltip.Root>
            <Tooltip.Trigger>
              {#snippet child({ props })}
                <Button
                  {...props}
                  variant="ghost"
                  size="icon-sm"
                  class="shrink-0 text-muted-foreground hover:text-foreground"
                  aria-label="Show grouping offsets help"
                >
                  <InfoIcon class="h-4 w-4" />
                </Button>
              {/snippet}
            </Tooltip.Trigger>
            <Tooltip.Content class="max-w-sm">
              <div class="grid gap-1.5">
                <strong>{helpCopy.groupingOffsets.title}</strong>
                <p>{helpCopy.groupingOffsets.description}</p>
                <p>{helpCopy.groupingOffsets.example}</p>
              </div>
            </Tooltip.Content>
          </Tooltip.Root>
        </h2>
        <div class="grid gap-2 sm:grid-cols-3">
          <div class="mb-auto grid gap-1">
            <Label for="temperature-step">Temperature step</Label>
            <Input
              bind:ref={temperatureStepInput}
              id="temperature-step"
              type="number"
              min="0"
              step="0.1"
              bind:value={appState.temperatureStep}
            />
          </div>
          <div class="mb-auto grid gap-1">
            <Label for="exposure-step">Exposure step</Label>
            <Input
              id="exposure-step"
              type="number"
              min="0"
              step="0.1"
              bind:value={appState.exposureStep}
            />
          </div>
          <div class="mb-auto grid gap-1">
            <Label for="gain-step">Gain step</Label>
            <Input id="gain-step" type="number" min="0" step="0.1" bind:value={appState.gainStep} />
          </div>
        </div>

        <Separator orientation="horizontal" />

        <h2 class="flex items-center gap-2 text-base font-medium">
          <span>Night name parsing</span>
          <Tooltip.Root>
            <Tooltip.Trigger>
              {#snippet child({ props })}
                <Button
                  {...props}
                  variant="ghost"
                  size="icon-sm"
                  class="shrink-0 text-muted-foreground hover:text-foreground"
                  aria-label="Show night name parsing help"
                >
                  <InfoIcon class="h-4 w-4" />
                </Button>
              {/snippet}
            </Tooltip.Trigger>
            <Tooltip.Content class="max-w-sm">
              <div class="grid gap-1.5">
                <strong>{helpCopy.nightNameParsing.title}</strong>
                <p>{helpCopy.nightNameParsing.description}</p>
                <p>{helpCopy.nightNameParsing.example}</p>
              </div>
            </Tooltip.Content>
          </Tooltip.Root>
        </h2>
        <Button
          variant="default"
          size="sm"
          onclick={() => {
            appState.nightPrefixes.push({
              text: '',
              type: 'Prefix',
              match_first: false
            });
          }}>Add Night Filter</Button
        >
        <div class="grid gap-4">
          {#each appState.nightPrefixes as filter, index (index)}
            <div class="flex items-center gap-2">
              <Input placeholder="Filter text" bind:value={filter.text} class="flex-1" />

              <Label>Prefix</Label>
              <Switch
                bind:checked={
                  () => filter.type === 'Suffix', (v) => (filter.type = v ? 'Suffix' : 'Prefix')
                }
              />
              <Label>Suffix</Label>

              <Label class="ml-2">Match first</Label>
              <Switch bind:checked={filter.match_first} />

              <XIcon
                class="h-4 w-4 cursor-pointer text-red-500"
                onclick={() => {
                  appState.nightPrefixes.splice(index, 1);
                }}
              />
            </div>
          {/each}
        </div>
        <Dialog.Footer>
          <Dialog.Close
            type="button"
            class={buttonVariants({ variant: 'outline' })}
            onclick={onNightConfigChange}
          >
            Close
          </Dialog.Close>
        </Dialog.Footer>
      </Dialog.Header>
    </Dialog.Content>
  </Dialog.Root>
</h2>
