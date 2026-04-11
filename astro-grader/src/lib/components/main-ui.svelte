<script lang="ts">
  import * as Resizable from '$/lib/components/ui/resizable';
  import ImageInfo from './preview/image-info.svelte';
  import Preview from './preview/preview.svelte';
  import Sidebar from './sidebar/index.svelte';
  import * as Separator from './ui/separator';
</script>

<Resizable.Pane defaultSize={60} class="flex w-full">
  <Resizable.PaneGroup direction="horizontal" class="flex h-full w-full" autoSaveId="main-ui">
    <Sidebar />
    <Resizable.Handle withHandle />
    <Preview />
  </Resizable.PaneGroup>
  <Separator.Root orientation="vertical" />
  <div class="flex h-full w-[20%] flex-col items-stretch justify-stretch">
    <ImageInfo />
  </div>
</Resizable.Pane>
