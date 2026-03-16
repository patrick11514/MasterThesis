<script lang="ts">
  import * as Sidebar from '$/lib/components/ui/sidebar';
  import { FolderPlus, Plus } from '@lucide/svelte';
  import { promptDirectory, promptFiles } from '../files/utils';
  import { Button } from './ui/button';
</script>

<Sidebar.Root>
  <Sidebar.Header>
    <Sidebar.Menu>
      <Sidebar.MenuItem class="flex items-center justify-center gap-2">
        <Button onclick={promptFiles} variant="outline" size="sm">
          <Plus class="h-4 w-4" /> Add new files
        </Button>
        <Button onclick={promptDirectory} variant="outline" size="sm">
          <FolderPlus class="h-4 w-4" />
        </Button>
      </Sidebar.MenuItem>
    </Sidebar.Menu>
  </Sidebar.Header>
  <Sidebar.Content>
    <Sidebar.Group />
    <Sidebar.Group />
  </Sidebar.Content>
  <Sidebar.Footer />
</Sidebar.Root>
