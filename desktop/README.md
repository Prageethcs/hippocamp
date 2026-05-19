# Hippocamp desktop app

Native desktop UI for [Hippocamp](../README.md) — local memory browser, AI-host configurator, and bundled MCP server.

Built with [Tauri 2](https://v2.tauri.app/) (Rust shell + WebView) and [Svelte 5](https://svelte.dev/) (TypeScript). Ships as `.dmg` for macOS today, `.exe` / `.deb` planned via the same codebase.

## Status

**Phase 1 — scaffold.** Empty Tauri + Svelte project. No Python sidecar yet, no UI screens yet. Ground truth for what's wired up:

- Tauri 2 + Svelte 5 + TypeScript scaffolded via `create-tauri-app`
- Window title, identifier (`run.hippocamp.desktop`), product name (`Hippocamp`) configured
- Both halves type-check / compile (`npm run check`, `cargo check`)

## Dev

```bash
cd desktop
npm install              # one-time
npm run tauri dev        # launches the app in dev mode (HMR)
```

## Build

```bash
npm run tauri build      # produces ./src-tauri/target/release/bundle/dmg/*.dmg (Mac)
```

The release build isn't signed or notarized yet — that comes in Phase 2.

## Layout

```
desktop/
  package.json           # frontend package (svelte, vite, tauri-cli)
  vite.config.js
  svelte.config.js
  src/                   # SvelteKit frontend (UI lives here)
  src-tauri/             # Rust shell
    Cargo.toml
    tauri.conf.json      # window, identifier, bundle config
    src/                 # Rust entry point + custom commands
    capabilities/        # Tauri permission manifest
    icons/               # placeholder icons (will be replaced)
```

## Roadmap

- **Phase 1 (in progress):** scaffold + memory browser UI + Python sidecar (FastAPI) + host-config buttons
- **Phase 2:** bundle standalone Python via Tauri sidecar, sign + notarize Mac builds
- **Phase 3:** auto-updates, landing page, multi-OS builds in CI
- **Phase 4:** beta + public launch

See the project [CHANGELOG](../CHANGELOG.md) for shipped versions.
