---
name: flutter-ui-ux-designer
description: Specialized Flutter frontend developer and UI/UX design expert for Select-to-Speech Linux application.
---

# Flutter & UX/UI Design Skill for Select-to-Speech

Use this skill whenever working on the Flutter frontend located in `src/ui/`.

## Workspace Context
- **Target Application**: Select-to-Speech Settings & System Tray UI (Linux Desktop).
- **Location**: `src/ui/` (Dart/Flutter).
- **Special Dependencies**:
  - Uses `tray_manager_patched` (`src/ui/tray_manager_patched`) via `src/ui/pubspec_overrides.yaml`. Never break or remove this override as it fixes C++ deprecation warnings on Linux and handles SVG tray icons.

## UI/UX Design System Guidelines

1. **Aesthetics & Theme**:
   - Deliver a modern, clean, premium Linux desktop UI (Material 3 compliant with dark mode support).
   - Use curated HSL dynamic color palettes, sleek subtle gradients, and rounded container cards instead of plain default widgets.
   - Avoid generic high-contrast stock colors (e.g., pure red/blue/green). Use cohesive theme tokens (`ColorScheme` from `Theme.of(context)`).

2. **Typography & Hierarchy**:
   - Maintain clear heading and label hierarchy.
   - Avoid hardcoded font sizes where possible; leverage `TextTheme` scale or clean relative layouts.

3. **Layout & Responsiveness**:
   - Design layouts using flexible widgets (`Expanded`, `Flexible`, `LayoutBuilder`, `ListView`).
   - Ensure setting cards and dynamic controls fit desktop screen sizes gracefully without overflow errors (`RenderFlex overflowed`).

4. **Animations & Micro-Interactions**:
   - Add micro-animations (hover effects, smooth page transitions, state change fades) to enhance user experience.
   - Use `AnimatedContainer`, `AnimatedSwitcher`, or standard `ImplicitlyAnimatedWidget` where appropriate.

5. **Screen Reader & Accessibility Compatibility (Mandatory)**:
   - **Semantics Widgets**: Ensure all custom interactive elements, icons, switches, buttons, and custom controls are wrapped in Flutter `Semantics` or `MergeSemantics` widgets with clear `label`, `hint`, and state descriptions (`enabled`, `toggled`, `selected`, `button: true`).
   - **Icon Accessibility**: Never use standalone `IconButton` or decorative `Icon` widgets without a `tooltip`, `Semantics(label: ...)`, or `excludeFromSemantics: true` (for purely visual decorative graphics).
   - **Focus Nodes & Keyboard Navigation**: Ensure all interactive controls have proper focus order and keyboard focus indicators so Linux desktop screen readers (e.g. Orca) and keyboard-only users can seamlessly navigate the UI.
   - **Contrast & Text Scaling**: Test that text labels remain legible under high contrast modes and when system screen reader / accessibility text scale factors are increased.

## Flutter Implementation Standards

1. **State & Architecture**:
   - Keep UI components decoupled and reusable in `src/ui/lib/`.
   - Maintain consistency with the existing backend IPC / settings model communicating with the FastAPI daemon.

2. **Verification & Quality**:
   - Run `flutter analyze` from `src/ui/` whenever modifying Flutter code.
   - Avoid direct edits to generated build artifacts or third-party packages inside `.pub-cache`.

3. **Changelog & Documentation**:
   - Remember to update `CHANGELOG.md` whenever adding new UI features or fixing UI/UX bugs.
