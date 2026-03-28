import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type WithoutChild<T> = T extends { child?: any } ? Omit<T, 'child'> : T;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type WithoutChildren<T> = T extends { children?: any } ? Omit<T, 'children'> : T;
export type WithoutChildrenOrChild<T> = WithoutChildren<WithoutChild<T>>;
export type WithElementRef<T, U extends HTMLElement = HTMLElement> = T & { ref?: U | null };

export const sortFunction = (a: string, b: string) =>
  a.localeCompare(b, undefined, { numeric: true });

export const getData = async <T>(url: string): Promise<T | undefined> => {
  try {
    const request = await fetch(url);
    if (!request.ok) {
      return undefined;
    }

    const contentType = request.headers.get('Content-Type');

    if (contentType === 'application/octet-stream') {
      return (await request.arrayBuffer()) as T;
    } else if (contentType === 'application/json') {
      return (await request.json()) as T;
    } else {
      return (await request.text()) as T;
    }
  } catch (e) {
    console.error(`Unable to fetch ${url}:`, e);
    return undefined;
  }
};
