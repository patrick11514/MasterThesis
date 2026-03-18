<script lang="ts">
  import MainUi from '$/lib/components/main-ui.svelte';
  import * as Resizable from '$/lib/components/ui/resizable';
</script>

<Resizable.PaneGroup direction="vertical" class="flex flex-col">
  <MainUi />
  <Resizable.Handle />
</Resizable.PaneGroup>
