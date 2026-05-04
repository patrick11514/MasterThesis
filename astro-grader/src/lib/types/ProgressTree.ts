/**
 * Generic recursive progress tree system to support:
 * - Simple linear progress bars (Group Frames)
 * - Detailed step tables (Calibrate Frames, Metrics)
 * - Hierarchical combined views (Run All Processes with nested sub-groups)
 */

export type ProgressStep = {
  type: 'progress';
  name: string;
  current: number;
  max: number;
} | {
  type: 'action';
  name: string;
  current?: number;
  max?: number;
};

export type ProgressGroup = {
  type: 'group';
  name: string;
  items: ProgressTreeItem[];
};

export type ProgressTreeItem = ProgressStep | ProgressGroup;

export type ProgressState = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export type ProgressTableItem = {
  item: ProgressTreeItem;
  state: ProgressState;
  startedAt: number | null;
  endedAt: number | null;
  error?: string;
  expanded?: boolean;
};

export type ProgressTree = {
  id: string;
  name: string;
  items: ProgressTableItem[];
  state: ProgressState;
  startedAt: number;
  endedAt: number | null;
};

/**
 * Helper to check if item is a group
 */
export const isGroup = (item: ProgressTreeItem): item is ProgressGroup => {
  return item.type === 'group';
};

/**
 * Helper to check if item is a step
 */
export const isStep = (item: ProgressTreeItem): item is ProgressStep => {
  return item.type === 'progress' || item.type === 'action';
};
