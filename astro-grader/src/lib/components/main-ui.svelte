<script lang="ts">
  import * as Resizable from '$/lib/components/ui/resizable';
  import Histogram from './histogram.svelte';
  import Preview from './preview.svelte';
  import Sidebar from './sidebar.svelte';
  import * as Separator from './ui/separator';
</script>

<Resizable.Pane defaultSize={60} class="flex w-full">
  <Resizable.PaneGroup direction="horizontal" class="flex h-full w-full" autoSaveId="main-ui">
    <Sidebar />
    <Resizable.Handle withHandle />
    <Preview />
    <Separator.Root orientation="vertical" />
    <Histogram />
  </Resizable.PaneGroup>
</Resizable.Pane>
