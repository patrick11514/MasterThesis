export {};

declare global {
  interface ObjectConstructor {
    entries<$Object extends object>(
      o: $Object
    ): { [$Key in keyof $Object]: [$Key, $Object[$Key]] }[keyof $Object][];
    fromEntries<$Array extends readonly (readonly [PropertyKey, unknown])[]>(
      entries: $Array
    ): {
      [$Key in $Array[number] as $Key[0]]: $Key[1];
    };
  }
}
