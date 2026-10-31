---
name: flutter-material3
description: Load this skill when working on the Flutter frontend of Select-to-Speech (src/ui/) — building or modifying UI components with Material 3, running Dart static analysis, touching the system tray icon, changing theming, or updating Flutter dependencies.
---

# Flutter Frontend with Material 3 (Select-to-Speech UI)

Scope: everything under `src/ui/` in this repository (Dart/Flutter desktop app, Linux/Windows).

## Project layout

- `src/ui/lib/main.dart` is the single app file: theme handling, settings UI, system tray integration, and the launcher/supervisor for the Python backend (FastAPI daemon over a Unix domain socket, probed at `http://localhost/status`).
- `src/ui/pubspec.yaml` declares dependencies (`http`, `tray_manager`, `path_provider`, `flutter_svg`, `dynamic_color`, `cupertino_icons`) and the `images/` asset directory.
- `src/ui/tray_manager_patched/` is a local fork of `tray_manager` overridden via `src/ui/pubspec_overrides.yaml`.

## Mandatory MCP & Analysis Workflow

1. **`dart` MCP Server & Static Analysis**:
   - Use for Dart language features, package management, analyzing code errors, running LSP commands, searching `pub.dev` packages, or inspecting the Flutter runtime (`analyze_files`, `pub`, `pub_dev_search`, `lsp`, `roots`, `read_package_uris`, `rip_grep_packages`, `hot_reload`, `hot_restart`, `widget_inspector`).
   - Whenever you modify any file in `src/ui/lib/`, run `analyze_files` (or `flutter analyze` from `src/ui/` in a shell) and fix all reported errors and warnings before considering the task done.
2. **`material3` MCP Server (`@weppa-cloud/material3-mcp-server`)**:
   - Use proactively when designing, modifying, or creating UI components in `src/ui/`.
   - Consult it for:
     - Canonical Material 3 component structure (Cards, Dialogs, Switches, Buttons, `SegmentedButton`, `NavigationBar`, etc.).
     - Design tokens and HCT-based `ColorScheme.fromSeed` generation.
     - Material Symbols / correct `Icons` usage.
     - WCAG accessibility and contrast verification.
   - Leverage it to avoid deprecated Flutter widgets and non-standard Material styling.

## Material 3 conventions

- Keep `useMaterial3: true` on `ThemeData`.
- The app follows the system theme via `themeModeNotifier` (`ThemeMode.system`); light/dark schemes must both be provided and tested for contrast.
- Seed the color scheme with `ColorScheme.fromSeed` rather than hardcoding raw colors; derive custom colors from the scheme so light/dark both work.
- Prefer current M3 widgets over M2 equivalents (`FilledButton`/`OutlinedButton`/`TextButton` over `RaisedButton`, `SegmentedButton` over `ToggleButtons`, `SearchBar`/`NavigationBar` where appropriate).

## Settings UI conventions (main.dart)

These conventions are settled design decisions from the settings UI; do not regress them:

- **Card structure**: every settings tab is a column of cards built with `_buildM3Card(title, icon, staggerIndex, children)`. The card header is a plain 26px icon in `cs.primary` followed by a `titleLarge` w700 title — icons are never wrapped in tinted containers/boxes. This is the ONLY place leading icons appear: individual settings inside a card must not have their own leading icons (settled design decision — do not add icon boxes to switch tiles, sliders, dropdowns, or field labels).
- **Switch tiles**: use `_buildM3SwitchTile` (row-based, no leading icon: title and `Switch` on one row, with the description rendered directly beneath the title inside the leading `Expanded` column, and an optional `footer` for extra content such as model download progress/badges). Never revert to `SwitchListTile`/`ListTile` for these: they vertically center the control across the whole tile, so on tall tiles (e.g. Neural Punctuation) the switch drifts out of alignment with the title.
- **Dropdowns**: `DropdownButtonFormField` fields must have no `prefixIcon` — omit the `decoration` entirely so the themed `InputDecorationTheme` applies, and put the label above with `_buildFieldLabel`. Sliders have no leading icon either: `_buildSlider` is label + reset/value badges only.
- **Shortcut fields**: `ShortcutRecorderWidget` renders keycap badges only — no leading/trailing icons of any kind (the pulsing border already signals recording state).
- **Color scheme**: `ColorScheme.fromSeed` must be generated with `DynamicSchemeVariant.content` (higher accent chroma, settled design decision — do not revert to the default tonalSpot variant) seeded from the OS accent color, and sliders use a 6px track height.
- **General tab layout**: four focused cards — Appearance (`t('appearance')`: GUI language + theme `SegmentedButton`), Performance (`t('performance')`: inference threads + detected CPU), Text Processing (`t('text_processing')`: text normalization + neural punctuation), Diagnostics (`t('diagnostics')`: debug logging). When adding a setting, place it in the matching card instead of creating catch-all cards.
- **Translations**: every user-visible string must exist in all four languages (`en`, `it`, `es`, `fr`) of the `translations` map in `main.dart`, including card titles and section names.
- **System accent color**: theming seeds `ColorScheme.fromSeed` from the OS accent color detected via `DynamicColorBuilder` plus the Linux watcher (`_initLinuxAccentColorWatcher`, XDG portal / `kdeglobals`). Do not remove either path or hardcode a seed.
- After editing Dart files, run `dart format` on them and `flutter analyze` (or `analyze_files`); both must be clean.

## tray_manager_patched — do not break

- `src/ui/tray_manager_patched` replaces `app_indicator_new` with `g_object_new` (resolving C++ deprecation warnings on Linux) and adds SVG tray icon support.
- Never remove the `tray_manager` path override in `src/ui/pubspec_overrides.yaml`, and keep the `lib` folder inside `src/ui/tray_manager_patched/` intact.
- Tray icons: use SVG assets from `src/ui/images/` through the patched package.

## Dependencies and backend integration

- Add or change Flutter dependencies only through `src/ui/pubspec.yaml`, then run `flutter pub get`. Never edit `pubspec.lock` by hand and never modify the patch fork's internals unless the task is specifically about it.
- The UI communicates with the backend over a UDS-based HTTP API. If you change a call to the Python backend, keep it consistent with the FastAPI endpoints in `src/select_to_speech/` (and vice versa).
