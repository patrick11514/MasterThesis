export type File = {
  path: string;
  name: string;
};

export type Files = {
  [night: string]: File[];
};
