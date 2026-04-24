<script lang="ts">
  import { getAppStateSync } from '$/lib/state.svelte';
  import type { CalibrationStorageMode } from '$/lib/types/CalibrationStorageMode';
  import type { NightPrefix } from '$/lib/types/NightPrefix';
  import { FolderOpenIcon, InfoIcon, SettingsIcon, XIcon } from '@lucide/svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { open } from '@tauri-apps/plugin-dialog';
  import { tick } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { cubicOut } from 'svelte/easing';
  import { fade, scale } from 'svelte/transition';
  import { Button } from '../ui/button';
  import { Input } from '../ui/input';
  import { Label } from '../ui/label';
  import * as Sidebar from '../ui/sidebar';
  import { Switch } from '../ui/switch';
  import * as Tooltip from '../ui/tooltip';

  const appState = getAppStateSync();
  let isDialogOpen = $state(false);
  let activePage = $state<
    'general' | 'processing.grouping' | 'processing.calibration' | 'file-list.night-parsing'
  >('general');
  let isSaving = $state(false);
  let configPath = $state('Loading...');

  let draftCalibrationStorageMode = $state<CalibrationStorageMode>('NextToOriginal');
  let draftTempFolderPath = $state('');
  let draftTemperatureStep = $state(1);
  let draftExposureStep = $state(0);
  let draftGainStep = $state(0);
  let draftNightPrefixes = $state<NightPrefix[]>([]);

  let tempFolderInput = $state<HTMLInputElement | null>(null);
  let temperatureStepInput = $state<HTMLInputElement | null>(null);

  const helpCopy = {
    general: {
      title: 'Temp folder',
      description:
        'This path is used when calibrated frames should be stored outside the source folder.',
      example:
        'Example: keep the path on a fast local disk if your source data lives on slower storage.'
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
    },
    calibrationMode: {
      title: 'Calibration storage mode',
      description:
        'This controls where calibrated frames are written or resolved from when running calibration.',
      example:
        'Example: Next to original writes frame_cal.fit beside the source file, while Temp folder uses the configured temp path.'
    }
  };

  const cloneNightPrefixes = (prefixes: NightPrefix[]) => prefixes.map((prefix) => ({ ...prefix }));

  const resetDraftState = () => {
    draftCalibrationStorageMode = appState.calibrationStorageMode;
    draftTempFolderPath = appState.tempFolderPath;
    draftTemperatureStep = appState.temperatureStep;
    draftExposureStep = appState.exposureStep;
    draftGainStep = appState.gainStep;
    draftNightPrefixes = cloneNightPrefixes(appState.nightPrefixes);
  };

  const loadConfigPath = async () => {
    try {
      configPath = await invoke<string>('config_path_get');
    } catch (error) {
      configPath = 'Unable to resolve config path';
      toast.error('Failed to load config location', {
        description: error as string
      });
    }
  };

  $effect(() => {
    if (!isDialogOpen) {
      return;
    }

    activePage = 'general';
    resetDraftState();
    void loadConfigPath();
  });

  const onSaveAndApply = async () => {
    isSaving = true;

    appState.calibrationStorageMode = draftCalibrationStorageMode;
    appState.tempFolderPath = draftTempFolderPath;
    appState.temperatureStep = draftTemperatureStep;
    appState.exposureStep = draftExposureStep;
    appState.gainStep = draftGainStep;
    appState.nightPrefixes = cloneNightPrefixes(draftNightPrefixes);

    await appState.saveConfig();
    appState.reApplyFilters();
    isSaving = false;
    isDialogOpen = false;
  };

  const onCancel = () => {
    isDialogOpen = false;
  };

  const onCopyConfigPath = async () => {
    try {
      await navigator.clipboard.writeText(configPath);
      toast.success('Config path copied');
    } catch (error) {
      toast.error('Failed to copy config path', {
        description: error as string
      });
    }
  };

  const onOpenConfigFolder = async () => {
    try {
      await invoke('config_open_folder');
      toast.success('Opened config folder');
    } catch (error) {
      toast.error('Failed to open config folder', {
        description: error as string
      });
    }
  };

  const onPickTempFolder = async () => {
    try {
      const directory = await open({ directory: true, defaultPath: draftTempFolderPath });

      if (typeof directory === 'string') {
        draftTempFolderPath = directory;
      }
    } catch (error) {
      toast.error('Failed to choose temp folder', {
        description: error as string
      });
    }
  };

  const onOpenOverlay = async () => {
    isDialogOpen = true;
    await tick();
    tempFolderInput?.focus();
  };

  const onOverlayKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      onCancel();
    }
  };
</script>

<Button variant="outline" size="sm" onclick={onOpenOverlay}>
  <SettingsIcon class="h-4 w-4" />
</Button>

{#if isDialogOpen}
  <button
    type="button"
    class="fixed inset-0 z-50 bg-black/50"
    aria-label="Close settings"
    onclick={onCancel}
    in:fade={{ duration: 180 }}
    out:fade={{ duration: 140 }}
  ></button>

  <div
    class="fixed top-1/2 left-1/2 z-50 flex h-[90vh] w-[95vw] max-w-none -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border bg-background p-0 shadow-lg md:w-[92vw]"
    role="dialog"
    aria-modal="true"
    aria-label="Settings"
    tabindex="-1"
    onkeydown={onOverlayKeyDown}
    onclick={(event) => event.stopPropagation()}
    in:scale={{ start: 0.96, duration: 200, easing: cubicOut }}
    out:scale={{ start: 0.96, duration: 140, easing: cubicOut }}
  >
    <div class="border-b px-6 py-4">
      <h2 class="text-lg font-semibold">Settings</h2>
    </div>

    <div class="grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-[280px_1fr]">
      <aside class="border-b p-2 md:border-r md:border-b-0" aria-label="Settings navigation">
        <Sidebar.SidebarGroup>
          <Sidebar.SidebarGroupLabel>General</Sidebar.SidebarGroupLabel>
          <Sidebar.SidebarGroupContent>
            <Sidebar.SidebarMenu>
              <Sidebar.SidebarMenuItem>
                <Sidebar.SidebarMenuButton
                  isActive={activePage === 'general'}
                  onclick={() => {
                    activePage = 'general';
                  }}
                >
                  General
                </Sidebar.SidebarMenuButton>
              </Sidebar.SidebarMenuItem>
            </Sidebar.SidebarMenu>
          </Sidebar.SidebarGroupContent>
        </Sidebar.SidebarGroup>

        <Sidebar.SidebarGroup>
          <Sidebar.SidebarGroupLabel>File list settings</Sidebar.SidebarGroupLabel>
          <Sidebar.SidebarGroupContent>
            <Sidebar.SidebarMenu>
              <Sidebar.SidebarMenuItem>
                <Sidebar.SidebarMenuButton
                  isActive={activePage === 'file-list.night-parsing'}
                  onclick={() => {
                    activePage = 'file-list.night-parsing';
                  }}
                >
                  Night name parsing
                </Sidebar.SidebarMenuButton>
              </Sidebar.SidebarMenuItem>
            </Sidebar.SidebarMenu>
          </Sidebar.SidebarGroupContent>
        </Sidebar.SidebarGroup>

        <Sidebar.SidebarGroup>
          <Sidebar.SidebarGroupLabel>Processing</Sidebar.SidebarGroupLabel>
          <Sidebar.SidebarGroupContent>
            <Sidebar.SidebarMenu>
              <Sidebar.SidebarMenuItem>
                <Sidebar.SidebarMenuButton
                  isActive={activePage === 'processing.grouping'}
                  onclick={() => {
                    activePage = 'processing.grouping';
                  }}
                >
                  Grouping
                </Sidebar.SidebarMenuButton>
              </Sidebar.SidebarMenuItem>
              <Sidebar.SidebarMenuItem>
                <Sidebar.SidebarMenuButton
                  isActive={activePage === 'processing.calibration'}
                  onclick={() => {
                    activePage = 'processing.calibration';
                  }}
                >
                  Calibration
                </Sidebar.SidebarMenuButton>
              </Sidebar.SidebarMenuItem>
            </Sidebar.SidebarMenu>
          </Sidebar.SidebarGroupContent>
        </Sidebar.SidebarGroup>
      </aside>

      <section class="overflow-y-auto p-6">
        {#if activePage === 'general'}
          <div class="grid gap-6">
            <h2 class="flex items-center gap-2 text-base font-medium">
              <span>General</span>
              <Tooltip.Root>
                <Tooltip.Trigger>
                  {#snippet child({ props })}
                    <Button
                      {...props}
                      variant="ghost"
                      size="icon-sm"
                      class="shrink-0 text-muted-foreground hover:text-foreground"
                      aria-label="Show temp folder help"
                    >
                      <InfoIcon class="h-4 w-4" />
                    </Button>
                  {/snippet}
                </Tooltip.Trigger>
                <Tooltip.Content class="max-w-sm">
                  <div class="grid gap-1.5">
                    <strong>{helpCopy.general.title}</strong>
                    <p>{helpCopy.general.description}</p>
                    <p>{helpCopy.general.example}</p>
                  </div>
                </Tooltip.Content>
              </Tooltip.Root>
            </h2>

            <div class="grid gap-3">
              <Label for="temp-folder-path">Temp folder</Label>
              <div class="flex flex-col gap-2 sm:flex-row">
                <Input
                  bind:ref={tempFolderInput}
                  id="temp-folder-path"
                  bind:value={draftTempFolderPath}
                  readonly
                  class="min-w-0 flex-1"
                />
                <Button variant="outline" size="sm" class="sm:w-fit" onclick={onPickTempFolder}>
                  <FolderOpenIcon class="h-4 w-4" />
                  Choose folder
                </Button>
              </div>
            </div>
          </div>
        {:else if activePage === 'processing.calibration'}
          <div class="grid gap-6">
            <h2 class="flex items-center gap-2 text-base font-medium">
              <span>Calibration storage mode</span>
              <Tooltip.Root>
                <Tooltip.Trigger>
                  {#snippet child({ props })}
                    <Button
                      {...props}
                      variant="ghost"
                      size="icon-sm"
                      class="shrink-0 text-muted-foreground hover:text-foreground"
                      aria-label="Show calibration storage help"
                    >
                      <InfoIcon class="h-4 w-4" />
                    </Button>
                  {/snippet}
                </Tooltip.Trigger>
                <Tooltip.Content class="max-w-sm">
                  <div class="grid gap-1.5">
                    <strong>{helpCopy.calibrationMode.title}</strong>
                    <p>{helpCopy.calibrationMode.description}</p>
                    <p>{helpCopy.calibrationMode.example}</p>
                  </div>
                </Tooltip.Content>
              </Tooltip.Root>
            </h2>

            <div class="grid gap-3">
              <Button
                variant={draftCalibrationStorageMode === 'NextToOriginal' ? 'default' : 'outline'}
                class="h-auto justify-start px-4 py-3 text-left"
                onclick={() => {
                  draftCalibrationStorageMode = 'NextToOriginal';
                }}
              >
                <div class="grid gap-1">
                  <span class="font-medium">Next to original</span>
                  <span class="text-xs text-muted-foreground">
                    Write ORIGINAL_NAME_cal.ORIGINAL_EXTENSION beside the source FITS file.
                  </span>
                </div>
              </Button>

              <Button
                variant={draftCalibrationStorageMode === 'TempFolder' ? 'default' : 'outline'}
                class="h-auto justify-start px-4 py-3 text-left"
                onclick={() => {
                  draftCalibrationStorageMode = 'TempFolder';
                }}
              >
                <div class="grid gap-1">
                  <span class="font-medium">Temp folder</span>
                  <span class="text-xs text-muted-foreground">
                    Resolve calibrated frames from the configured temp folder.
                  </span>
                </div>
              </Button>
            </div>
          </div>
        {:else if activePage === 'processing.grouping'}
          <div class="grid gap-6">
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
                  bind:value={draftTemperatureStep}
                />
              </div>
              <div class="mb-auto grid gap-1">
                <Label for="exposure-step">Exposure step</Label>
                <Input
                  id="exposure-step"
                  type="number"
                  min="0"
                  step="0.1"
                  bind:value={draftExposureStep}
                />
              </div>
              <div class="mb-auto grid gap-1">
                <Label for="gain-step">Gain step</Label>
                <Input id="gain-step" type="number" min="0" step="0.1" bind:value={draftGainStep} />
              </div>
            </div>
          </div>
        {:else if activePage === 'file-list.night-parsing'}
          <div class="grid gap-6">
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
              class="w-fit"
              onclick={() => {
                draftNightPrefixes.push({
                  text: '',
                  type: 'Prefix',
                  match_first: false
                });
              }}
            >
              Add Night Filter
            </Button>

            <div class="grid gap-4">
              {#each draftNightPrefixes as filter, index (index)}
                <div class="flex flex-wrap items-center gap-2">
                  <Input
                    placeholder="Filter text"
                    bind:value={filter.text}
                    class="min-w-56 flex-1"
                  />

                  <Label>Prefix</Label>
                  <Switch
                    bind:checked={
                      () => filter.type === 'Suffix', (v) => (filter.type = v ? 'Suffix' : 'Prefix')
                    }
                  />
                  <Label>Suffix</Label>

                  <Label class="ml-2">Match first</Label>
                  <Switch bind:checked={filter.match_first} />

                  <Button
                    variant="ghost"
                    size="icon-sm"
                    class="text-red-500 hover:text-red-600"
                    aria-label="Remove night filter"
                    onclick={() => {
                      draftNightPrefixes.splice(index, 1);
                    }}
                  >
                    <XIcon class="h-4 w-4" />
                  </Button>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </section>
    </div>

    <div class="border-t px-6 py-4">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div class="min-w-0 rounded-lg border p-3">
          <h3 class="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Config location
          </h3>
          <p class="mt-1 text-xs break-all text-muted-foreground">{configPath}</p>
          <div class="mt-2 flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onclick={onCopyConfigPath}>Copy path</Button>
            <Button variant="outline" size="sm" onclick={onOpenConfigFolder}>
              <FolderOpenIcon class="h-4 w-4" />
              Open folder
            </Button>
          </div>
        </div>

        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="outline" onclick={onCancel}>Cancel</Button>
          <Button onclick={onSaveAndApply} disabled={isSaving}>
            {isSaving ? 'Saving...' : 'Save & Apply'}
          </Button>
        </div>
      </div>
    </div>
  </div>
{/if}
