# RouteWright Design System

Design-token architecture established in Phase 2a. Tokens live in two
places: CSS custom properties in `app/globals.css` (for theme-able
values) and Tailwind config extensions in `tailwind.config.ts` (for
utility aliases that reference those properties).

---

## How to redesign

**Change a color, radius, or shadow for the entire app:**
Edit `--color-*`, `--radius-*`, or `--shadow-*` in the `:root` block of
`app/globals.css`. Every component that references the token updates
automatically — no component files need to touch.

**Change a single component:**
Override the token class on that element. For example, to make one
button use a different shade, add a raw Tailwind class alongside the
token class.

**Add a new token:**
1. Add the CSS custom property in `globals.css :root`.
2. Add the Tailwind alias in `tailwind.config.ts` `theme.extend.colors`
   (or `boxShadow`, `borderRadius` as appropriate).
3. Use it in components via the Tailwind utility.

---

## Color tokens

All token values map 1:1 to Tailwind defaults as of Phase 2a.
Phase 2b will refine values by editing the `:root` block only.

### Surfaces
| Token class       | CSS var              | Current value | Semantic role            |
|-------------------|----------------------|---------------|--------------------------|
| `bg-bg-base`      | `--color-bg-base`    | zinc-50       | Page canvas (body bg)    |
| `bg-bg-elevated`  | `--color-bg-elevated`| white         | Cards, dots, edit inputs |

### Text
| Token class          | CSS var                   | Current value | Semantic role                    |
|----------------------|---------------------------|---------------|----------------------------------|
| `text-text-primary`  | `--color-text-primary`    | zinc-900      | Headings, key data               |
| `text-text-secondary`| `--color-text-secondary`  | zinc-600      | Body copy, leg summaries         |
| `text-text-tertiary` | `--color-text-tertiary`   | zinc-500      | Supporting labels                |
| `text-text-muted`    | `--color-text-muted`      | zinc-400      | Captions, icons, timestamps      |
| `text-text-ghost`    | `--color-text-ghost`      | zinc-300      | Drag handle, separator dots      |
| `text-text-label`    | `--color-text-label`      | zinc-700      | Form field labels                |

### Borders
| Token class            | CSS var                  | Current value | Semantic role           |
|------------------------|--------------------------|---------------|-------------------------|
| `border-border-subtle` | `--color-border-subtle`  | zinc-200      | Timeline dotted line    |
| `border-border-default`| `--color-border-default` | zinc-300      | Input borders           |

### Accent (blue)
| Token class              | CSS var                    | Current value | Semantic role                   |
|--------------------------|----------------------------|---------------|---------------------------------|
| `*-accent`               | `--color-accent`           | blue-600      | Primary buttons, links          |
| `*-accent-hover`         | `--color-accent-hover`     | blue-700      | Hover state for accent bg       |
| `*-accent-strong`        | `--color-accent-strong`    | blue-800      | Hover state for text links      |
| `*-accent-emphasis`      | `--color-accent-emphasis`  | blue-500      | Timeline dot, focus rings       |
| `*-accent-border`        | `--color-accent-border`    | blue-400      | Active edit-input border        |
| `*-accent-faint`         | `--color-accent-faint`     | blue-200      | Drag overlay border             |

### Semantic states
| Token class          | CSS var               | Semantic role          |
|----------------------|-----------------------|------------------------|
| `bg-error-bg`        | `--color-error-bg`    | Error banner bg        |
| `border-error-border`| `--color-error-border`| Error banner border    |
| `text-error-text`    | `--color-error-text`  | Error text             |
| `bg-warning-bg`      | `--color-warning-bg`  | Warning banner bg      |
| `border-warning-border`|`--color-warning-border`| Warning banner border|
| `text-warning-text`  | `--color-warning-text`| Warning text           |
| `text-warning-icon`  | `--color-warning-icon`| Warning icon / caption |
| `text-warning-strong`| `--color-warning-strong`| Degraded leg text    |

---

## Typography utilities

Defined in `@layer components` in `globals.css`. These combine size and
weight into a single semantic class so components don't repeat ad-hoc
combinations like `text-sm font-medium`.

| Utility         | Expands to                          | Role                              |
|-----------------|-------------------------------------|-----------------------------------|
| `text-display`  | `text-3xl font-bold`                | Page title ("RouteWright")        |
| `text-body`     | `text-sm`                           | Default body copy                 |
| `text-body-strong`| `text-sm font-medium`             | Emphasised body (stop names, etc.)|
| `text-caption`  | `text-xs`                           | Hint text, captions               |
| `text-time`     | `text-sm font-semibold tabular-nums`| Clock values in the timeline      |

**Phase 2b intent — font family:**
The target font stack is system-native SF Pro on Apple and Segoe UI on
Windows. The CSS var is documented in `globals.css` but not applied yet
to avoid non-Apple platform changes before launch:

```css
--font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
```

To activate: add `fontFamily: { sans: ['var(--font-sans)'] }` to
`tailwind.config.ts`.

---

## Radius tokens

| CSS var        | Value     | Maps to Tailwind | Used for               |
|----------------|-----------|------------------|------------------------|
| `--radius-sm`  | 0.25rem   | `rounded`        | Inline / small elements|
| `--radius-md`  | 0.375rem  | `rounded-md`     | Inputs, buttons        |
| `--radius-lg`  | 0.5rem    | `rounded-lg`     | Larger containers      |

`rounded-md` and `rounded-lg` in Tailwind are overridden in
`tailwind.config.ts` to reference the CSS vars. Changing `--radius-md`
in Phase 2b will update every input and button at once.

---

## Shadow tokens

| Token class       | CSS var            | Current value  | Role              |
|-------------------|--------------------|----------------|-------------------|
| `shadow-subtle`   | `--shadow-subtle`  | none           | Resting card state|
| `shadow-raised`   | `--shadow-raised`  | shadow-md      | Hover / focus     |
| `shadow-floating` | `--shadow-floating`| shadow-lg      | Drag overlay      |

`shadow-lg` in the drag overlay is replaced by `shadow-floating`.
Currently there are no resting card shadows (`shadow-subtle: none`).
Phase 2b may introduce a subtle elevation.

---

## Design intent (Phase 2b brief)

The brief is Notion / macOS style: calm, not loud. Refined, not
minimal. The token values above are the current baseline. Phase 2b
changes will be:
- Background: slightly warmer off-white (stone-50 vs zinc-50)
- Border radii: 8px across the board for a softer feel
- Accent: possibly a slightly less saturated blue
- Font: activate the system-native stack (SF Pro on Apple)

These changes happen by editing `:root` in `globals.css` only.
No component files need to change.
