import type { File } from '../types/File';
import type { FileType } from '../types/FileType';

export type Files = {
  [night: string]: File[];
};

export const FILE_TYPES = [
  'Bias',
  'Dark',
  'Flat',
  'Light',
  'MasterDark',
  'MasterFlat',
  'MasterBias'
] as const satisfies FileType[];

export const FILE_COLORS = {
  Light: 'text-yellow-400',
  Bias: 'text-green-500',
  Dark: 'text-slate-600',
  Flat: 'text-amber-500',
  MasterBias: 'text-green-700',
  MasterDark: 'text-slate-800',
  MasterFlat: 'text-amber-700'
} satisfies Record<FileType, string>;

export const FILE_BADGES = {
  Light: 'border-yellow-400 bg-yellow-100 dark:bg-yellow-900/50',
  Bias: 'border-green-500 bg-green-100 dark:bg-green-900/50',
  Dark: 'border-slate-500 bg-slate-100 dark:bg-slate-700/50',
  Flat: 'border-amber-500 bg-amber-100 dark:bg-amber-900/50',
  MasterBias: 'border-green-700 bg-green-200 dark:bg-green-900/50',
  MasterDark: 'border-slate-700 bg-slate-200 dark:bg-slate-700/50',
  MasterFlat: 'border-amber-700 bg-amber-200 dark:bg-amber-900/50'
};
