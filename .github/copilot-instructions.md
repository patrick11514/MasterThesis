# Copilot Test Instructions

Always install new shadcn-svelte components with `pnpx shadcn-svelte@latest add %component% -o -y` (example: `pnpx shadcn-svelte@latest add button -o -y`). The `-o` flag overwrites existing component files, and `-y` auto-confirms prompts.

Use this repository verification flow when checking code integrity. Start with Rust, regenerate shared types, then validate the Svelte frontend.

## Verification Order

1. Run backend tests:
   ```bash
   cd src-tauri && cargo test
   ```

2. Regenerate frontend types from Rust exports:
   ```bash
   cd src-tauri && cargo test export_bindings
   ```
   This is also exposed at the repo root as:
   ```bash
   pnpm run sync:types
   ```

3. Run frontend validation:
   ```bash
   pnpm run check
   ```
   This runs `svelte-kit sync` and `svelte-check`.

4. If you want the full integrity pass in one command, use:
   ```bash
   pnpm run verify
   ```

## What to watch for

- If Rust tests fail, fix the backend first before regenerating types.
- Always rerun type generation after changing exported Rust structs or enums under `src-tauri/src`.
- If frontend checks fail, prefer fixing the generated type usage in `src/lib` rather than hand-editing generated files in `src/lib/types`.
- Generated frontend types in `src/lib/types/*.ts` should be treated as derived output.

## Current Known Pattern

- Rust `ts-rs` exports are the source of truth for shared types.
- `sync:types` must run before frontend type checks whenever exported Rust types change.
- The most useful final signal for an agent is a clean run of `cargo test`, `sync:types`, and `check` in that order.
