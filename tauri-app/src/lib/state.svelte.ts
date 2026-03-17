import type { File } from './files/types';

class AppState {
  public files = $state<File[]>([]);
}

export const appState = new AppState();
