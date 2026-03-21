<script lang="ts">
  import { getAppState } from '$/lib/state.svelte';
  import { SettingsIcon, XIcon } from '@lucide/svelte';
  import { Button, buttonVariants } from '../ui/button';
  import * as Dialog from '../ui/dialog';
  import { Input } from '../ui/input';
  import { Label } from '../ui/label';
  import { Switch } from '../ui/switch';

  const appState = await getAppState();

  const onNightConfigChange = async () => {
    await appState.saveConfig();

    appState.reApplyFilters();
  };
</script>

<h2 class="text-lg">
  Night list
  <Dialog.Root>
    <Dialog.Trigger>
      <Button variant="outline" size="sm">
        <SettingsIcon class="h-4 w-4" />
      </Button>
    </Dialog.Trigger>
    <Dialog.Content>
      <Dialog.Header>
        <Dialog.Title>Night Settings</Dialog.Title>
        <Dialog.Description>
          Configure how the app identifies nights based on the file path. For example if you have
          files named like <code>Night_2024-01-01/file.fits</code>, you can set the prefix to
          <code>Night_</code>
          and then the nights will be idetified as <code>2024-01-01</code>.
        </Dialog.Description>
        <Button
          variant="default"
          size="sm"
          onclick={() => {
            appState.nightPrefixes.push({
              text: '',
              type: 'Prefix'
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
