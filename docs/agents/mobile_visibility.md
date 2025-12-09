# Mobile Visibility Rules (≤768px)

## File Locations
- **CSS**: `src/static/css/input.css` (@media queries) + compiled output
- **Home**: `src/templates/app/home.html` + `src/templates/app/components/home_grid.html`
- **Media list/grid**: `src/templates/app/media_list.html` + `src/templates/app/components/media_grid_items.html` + `media_card.html`

## Visibility Control System
All mobile hiding uses data attributes + CSS:
- `data-*-mode="conditional"` → hidden by default on mobile
- `data-mobile-show="true"` → override to show
- `data-mobile-hide-on-mobile="true"` → always hide on mobile

## Home Screen (In Progress Grid)
**Progress row under posters:**
- Uses `data-progress-mode="conditional"` in `home_grid.html`
- Only visible when sort = `progress` (via `data-mobile-show="true"`)
- `+/-` buttons (`.progress-adjust-btn` in `progress_changer.html`) stripped on mobile

**Duplicate summary items** (Total Progress, Rating, repeats):
- Use `data-mobile-hide-on-mobile="true"` → hidden on mobile, visible on desktop

**Action overlay** (Track/Lists/History):
- Suppressed on touch devices when `user.clickable_media_cards` enabled (via `pointer-coarse:hidden`)

## Media List/Grid Cards
**Chips** (`media_card.html`):
- All use `data-*-mode="conditional"` from `media_grid_items.html`
- Only the active sort chip shows (via `data-mobile-show="true"`):
  - **Score chip** → visible when sort = `score`
  - **Progress chip** → visible when sort = `progress`
  - **Time-left chip** (TV only) → visible when sort = `time_left`

**Status chip**:
- Gets `data-mobile-hide-on-mobile="true"` when sorting by `score`, `time_left`, or `progress` (prevents overlap with sort chip)

## Under-Poster Content
- Layout/padding shrinks on mobile
- Progress sections: hidden unless `data-mobile-show="true"`, `+/-` buttons removed
- Text blocks: remain visible unless marked with `data-mobile-hide-on-mobile="true"` or Tailwind `hidden sm:block`