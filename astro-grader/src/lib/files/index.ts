import { Channel, invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';
import type { File } from '../types/File';
import type { NightPrefix } from '../types/NightPrefix';
import { sortFunction } from '../utils';

const TARGET_EXTENSIONS = ['fits'];
const DEFAULT_NIGHT_NAME = 'Unsorted';

/*
 * Prompts the user to select files and returns an array of File objects.
 * Each File object contains the path and name of the file.
 * If the user cancels the file selection, it returns undefined.
 */
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

  return await invoke<File[]>('file_picker_convert', {
    files
  });
};

/*
 * Prompts the user to select a directory and returns an array of File objects for all files in that directory and its subdirectories that match the TARGET_EXTENSIONS.
 * Each File object contains the path and name of the file.
 * If the user cancels the directory selection, it returns undefined.
 */
export const promptDirectory = async (channel: Channel<number>) => {
  const directory = await open({
    directory: true
  });

  if (!directory) {
    return;
  }

  return await invoke<File[]>('file_picker_recursive', {
    extensions: TARGET_EXTENSIONS,
    directory,
    channel
  });
};

/*
 * Parses an array of File objects and groups them based on the provided NightPrefix filters.
 * Iterates through all path segments and COMBINES all matching filters into a single group key.
 * Example: "/Orion Panel 1/Session_2026_10_02/" -> "Orion Panel 1 - 2026_10_02"
 */
export const parseFiles = (files: File[], filters: NightPrefix[]) => {
  const parsedFiles: Record<string, File[]> = {};

  for (const file of files) {
    // We split the path and remove any empty strings (caused by leading/trailing slashes)
    // We do NOT reverse it here, so the hierarchy reads left-to-right (e.g., Target -> Session)
    const paths = file.path.split('/').filter(Boolean);

    // Use an array to accumulate all matched parts for this specific file
    const matchedParts: string[] = [];

    for (const path of paths) {
      for (const filter of filters) {
        if (filter.type === 'Prefix' && path.startsWith(filter.text)) {
          // Extract the string without the prefix and save it
          matchedParts.push(path.slice(filter.text.length));
          break; // Break the filter loop (move to the next path segment)
        } else if (filter.type === 'Suffix' && path.endsWith(filter.text)) {
          // Extract the string without the suffix and save it
          matchedParts.push(path.slice(0, -filter.text.length));
          break; // Break the filter loop
        }
      }
      // Note: We removed `if (found) break;` from here so it continues checking all folders!
    }

    // Combine all found matches with a clean separator, or fallback to Unsorted
    const groupKey = matchedParts.length > 0 ? matchedParts.join(' - ') : DEFAULT_NIGHT_NAME;

    // Initialize array if it doesn't exist, then push
    if (!parsedFiles[groupKey]) {
      parsedFiles[groupKey] = [];
    }
    parsedFiles[groupKey].push(file);
  }

  // Sorting
  // 1. Each group by name (and the Unsorted group should be first)
  // 2. Sort files in each group by name
  const sortedParsedFiles: Record<string, File[]> = {};

  if (parsedFiles[DEFAULT_NIGHT_NAME]) {
    sortedParsedFiles[DEFAULT_NIGHT_NAME] = parsedFiles[DEFAULT_NIGHT_NAME].sort((a, b) =>
      sortFunction(a.name, b.name)
    );
  }

  const sortedKeys = Object.keys(parsedFiles)
    .filter((key) => key !== DEFAULT_NIGHT_NAME)
    .sort((a, b) => sortFunction(a, b));

  for (const key of sortedKeys) {
    sortedParsedFiles[key] = parsedFiles[key].sort((a, b) => sortFunction(a.name, b.name));
  }

  return sortedParsedFiles;
};
