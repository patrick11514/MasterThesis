import { invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';

const TARGET_EXTENSIONS = ['fits'];

export const promptFiles = async () => {
  const files = await open({
    multiple: true,
    filters: [
      {
        name: 'Astronomical images',
        extensions: TARGET_EXTENSIONS
      }
    ]
  });

  console.log(files);
};

export const promptDirectory = async () => {
  const directory = await open({
    directory: true
  });

  if (!directory) {
    return;
  }

  const files = await invoke('recursive_files', {
    extensions: TARGET_EXTENSIONS,
    directory
  });
};
