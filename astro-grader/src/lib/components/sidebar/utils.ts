import type { AppStateType } from '$/lib/state.svelte';
import type { File } from '$/lib/types/File';

export const isShown = (appState: AppStateType, file: File) => {
  const type = file.type;
  return appState.framesShown[type];
};
