import { Channel, invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';
import type { File } from './types';

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

  if (!files) return;

  return files.map(toFile);
};

export const promptDirectory = async (channel: Channel<number>) => {
  const directory = await open({
    directory: true
  });

  if (!directory) {
    return;
  }

  const files = await invoke<string[]>('recursive', {
    extensions: TARGET_EXTENSIONS,
    directory,
    channel
  });

  return files.map(toFile);
};

const toFile = (path: string): File => {
  const name = path.split('/').slice(-1)[0];

  return {
    path,
    name
  };
};
