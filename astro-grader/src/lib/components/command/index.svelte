<script lang="ts">
  import CalculatorIcon from '@lucide/svelte/icons/calculator';
  import CalendarIcon from '@lucide/svelte/icons/calendar';
  import CreditCardIcon from '@lucide/svelte/icons/credit-card';
  import SettingsIcon from '@lucide/svelte/icons/settings';
  import SmileIcon from '@lucide/svelte/icons/smile';
  import UserIcon from '@lucide/svelte/icons/user';
  import * as Command from '../ui/command';

  let open = $state(false);

  function handleKeydown(e: KeyboardEvent) {
    const ctrl = e.ctrlKey;
    const meta = e.metaKey;
    const shift = e.shiftKey;

    const K = e.key === 'k' || e.key === 'K';
    const P = e.key === 'p' || e.key === 'P';

    if (
      //
      ((ctrl || meta) && K) ||
      ((ctrl || meta) && shift && P)
    ) {
      e.preventDefault();
      open = !open;
    }
  }
</script>

<svelte:document onkeydown={handleKeydown} />

<Command.Dialog bind:open>
  <Command.Input placeholder="Type a command or search..." />
  <Command.List>
    <Command.Empty>No results found.</Command.Empty>
    <Command.Group heading="Suggestions">
      <Command.Item>
        <CalendarIcon class="me-2 size-4" />
        <span>Calendar</span>
      </Command.Item>
      <Command.Item>
        <SmileIcon class="me-2 size-4" />
        <span>Search Emoji</span>
      </Command.Item>
      <Command.Item>
        <CalculatorIcon class="me-2 size-4" />
        <span>Calculator</span>
      </Command.Item>
    </Command.Group>
    <Command.Separator />
    <Command.Group heading="Settings">
      <Command.Item>
        <UserIcon class="me-2 size-4" />
        <span>Profile</span>
        <Command.Shortcut>⌘P</Command.Shortcut>
      </Command.Item>
      <Command.Item>
        <CreditCardIcon class="me-2 size-4" />
        <span>Billing</span>
        <Command.Shortcut>⌘B</Command.Shortcut>
      </Command.Item>
      <Command.Item>
        <SettingsIcon class="me-2 size-4" />
        <span>Settings</span>
        <Command.Shortcut>⌘S</Command.Shortcut>
      </Command.Item>
    </Command.Group>
  </Command.List>
</Command.Dialog>
