# dArchiva Frontend Developer Guide

## Table of Contents

1. [Overview](#overview)
2. [Tech Stack](#tech-stack)
3. [Project Structure](#project-structure)
4. [Local Development](#local-development)
5. [API Client](#api-client)
6. [Feature Module Pattern](#feature-module-pattern)
7. [Modal System](#modal-system)
8. [Global State](#global-state)
9. [Adding a New Feature](#adding-a-new-feature)
10. [Component Conventions](#component-conventions)
11. [Styling](#styling)
12. [Environment Variables](#environment-variables)

---

## Overview

`darchiva-ui/` is a React 18 single-page application. It communicates with the FastAPI backend exclusively via REST (no WebSockets). All remote state is managed by TanStack Query; local UI state lives in Zustand via `useStore`.

---

## Tech Stack

| Concern | Library |
|---|---|
| Framework | React 18 + Vite |
| Routing | React Router v6 |
| Server state | TanStack Query (React Query) v5 |
| Client state | Zustand |
| UI components | shadcn/ui (Radix + Tailwind) |
| Forms | react-hook-form + zod |
| Animation | Framer Motion |
| HTTP | Axios (`apiClient`) |
| Notifications | sonner |
| Icons | Lucide React |
| Type-check | TypeScript strict mode |

---

## Project Structure

```
darchiva-ui/
├── src/
│   ├── App.tsx                  # Route definitions
│   ├── main.tsx                 # React root + QueryClient + providers
│   ├── components/
│   │   ├── ModalManager.tsx     # Central modal dispatcher (all 35 modal IDs)
│   │   ├── Sidebar.tsx
│   │   └── ui/                  # shadcn/ui primitives
│   ├── features/                # One dir per domain (see below)
│   │   ├── <feature>/
│   │   │   ├── api.ts           # TanStack Query hooks + types
│   │   │   ├── components/      # Feature-specific components
│   │   │   │   └── modals/      # Feature modal components
│   │   │   ├── types/           # TypeScript interfaces (if complex)
│   │   │   └── index.ts         # Re-exports
│   ├── hooks/
│   │   └── useStore.ts          # Zustand store
│   ├── lib/
│   │   ├── api-client.ts        # Axios instance with auth interceptor
│   │   └── utils.ts             # cn(), formatRelativeTime(), etc.
│   ├── pages/                   # Top-level route components
│   └── types/
│       └── index.ts             # Shared TypeScript interfaces
```

### Feature Directories

| Directory | Domain |
|---|---|
| `features/cases` | Cases, bundles |
| `features/documents` | Document CRUD, viewer, page management |
| `features/encryption` | Key management, encrypted document list |
| `features/forms` | Form extraction queue and templates |
| `features/groups` | Group CRUD, member management |
| `features/home` | Dashboard, favorites, activity feed |
| `features/ingestion` | Ingestion sources, jobs, batches |
| `features/notifications` | Notification feed |
| `features/portfolios` | Portfolio CRUD |
| `features/roles` | Role and permission management |
| `features/routing` | Routing rule CRUD and testing |
| `features/scanning-ops` | Scan station operator UI |
| `features/scanning-projects` | Project management, fleet view |
| `features/search` | Full-text + semantic search |
| `features/users` | User CRUD, profile, activity |

---

## Local Development

```bash
cd darchiva-ui
npm install

# Point at local API
cp .env.example .env.local
# Set VITE_API_BASE_URL=http://localhost:8000

npm run dev        # Vite dev server → http://localhost:5173
npm run build      # Production build → dist/
npm run typecheck  # tsc --noEmit
```

### Proxy

The Vite dev server does NOT proxy `/api/*` automatically. Either set `VITE_API_BASE_URL` to the running backend, or add a proxy in `vite.config.ts`:

```ts
// vite.config.ts
export default defineConfig({
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```

---

## API Client

`src/lib/api-client.ts` exports a pre-configured Axios instance:

```ts
import { apiClient } from '@/lib/api-client';

// GET
const { data } = await apiClient.get<MyType>('/endpoint', { params: { page: 1 } });

// POST
const { data } = await apiClient.post<MyType>('/endpoint', body);

// PATCH
const { data } = await apiClient.patch<MyType>('/endpoint/id', partialBody);

// DELETE
await apiClient.delete('/endpoint/id');
```

The instance:
- Sets `baseURL` from `VITE_API_BASE_URL` (defaults to `''` so paths are relative)
- Injects `Authorization: Bearer <token>` from localStorage on every request
- Redirects to `/login` on 401

---

## Feature Module Pattern

Every feature follows this pattern:

### `api.ts` — hooks and types

```ts
// types
export interface MyItem { id: string; name: string; ... }

// query keys (stable, used for cache invalidation)
export const myKeys = {
  all: ['myFeature'] as const,
  list: () => [...myKeys.all, 'list'] as const,
  detail: (id: string) => [...myKeys.all, id] as const,
};

// read hook
export function useMyItems() {
  return useQuery({
    queryKey: myKeys.list(),
    queryFn: async () => {
      const { data } = await apiClient.get<MyItem[]>('/my-items');
      return data;
    },
  });
}

// mutation hook
export function useCreateMyItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { name: string }) => {
      const { data } = await apiClient.post<MyItem>('/my-items', input);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: myKeys.all });
    },
  });
}
```

### `index.ts` — barrel exports

```ts
export * from './api';
export * from './types';
```

---

## Modal System

All modals go through `ModalManager.tsx`. This keeps a single overlay layer and avoids z-index battles.

### Opening a modal

```ts
import { useStore } from '@/hooks/useStore';

const { openModal } = useStore();

// Simple modal (no data)
openModal('create-portfolio');

// Modal with data payload
openModal('edit-routing-rule', routingRuleObject);
openModal('view-case', caseObject);
```

### Adding a new modal

1. Create the modal component in `features/<feature>/components/modals/MyModal.tsx`:

```tsx
interface Props {
  onClose: () => void;
  item: MyItem;           // from modalData
}

export function MyModal({ onClose, item }: Props) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="glass-card w-full max-w-md p-6">
        {/* content */}
        <button onClick={onClose} className="btn-secondary">Close</button>
      </div>
    </div>
  );
}
```

2. Add the handler to `src/components/ModalManager.tsx`:

```tsx
import { MyModal } from '@/features/myFeature/components/modals/MyModal';
import type { MyItem } from '@/features/myFeature/api';

// inside ModalManager():
if (activeModal === 'my-modal-id')
  return <MyModal onClose={closeModal} item={modalData as MyItem} />;
```

3. Open it anywhere with `openModal('my-modal-id', item)`.

### Modal ID registry

All 35 currently registered modal IDs (managed in `ModalManager.tsx`):

`upload` · `create-folder` · `filter-documents` · `sort-documents` · `view-encrypted-document` · `create-case` · `view-case` · `create-bundle` · `add-documents-to-case` · `manage-case-access` · `edit-case-tags` · `case-filters` · `case-options` · `create-portfolio` · `view-portfolio` · `portfolio-options` · `add-routing-rule` · `edit-routing-rule` · `delete-routing-rule` · `test-routing-rule` · `routing-rule-options` · `add-ingestion-source` · `ingestion-source-settings` · `ingestion-source-options` · `create-project` · `create-user` · `edit-user` · `create-group` · `edit-group` · `view-group-members` · `create-role` · `edit-role` · `notifications` · `user-profile` · `activity-history` · `manage-favorites`

---

## Global State

`src/hooks/useStore.ts` is a Zustand store. Keep it small — only truly cross-cutting state lives here.

Current slices:

| Key | Type | Purpose |
|---|---|---|
| `activeModal` | `string \| null` | Currently open modal ID |
| `modalData` | `unknown` | Data payload for the open modal |
| `openModal(id, data?)` | function | Open a modal |
| `closeModal()` | function | Close the modal and clear data |
| `currentPageIndex` | number | Document viewer current page |
| `zoom` / `rotation` | number | Viewer zoom and rotation state |
| `viewerMode` | `'single'\|'thumbnails'` | Viewer display mode |
| `pages` | `ViewerPage[]` | Pages loaded in the viewer |

Do **not** put server state (API responses) in Zustand — that belongs in TanStack Query.

---

## Adding a New Feature

### 1. Create the API module

```bash
mkdir -p src/features/my-feature/components/modals
touch src/features/my-feature/api.ts
touch src/features/my-feature/index.ts
```

### 2. Define types and hooks in `api.ts`

Follow the pattern in [Feature Module Pattern](#feature-module-pattern) above.

### 3. Create a page component

```bash
touch src/pages/MyFeature.tsx
```

Import hooks from `@/features/my-feature`, render data from TanStack Query.

### 4. Register the route

In `src/App.tsx`:

```tsx
import { MyFeature } from './pages/MyFeature';

// inside <Routes>:
<Route path="/my-feature" element={<MyFeature />} />
```

### 5. Add sidebar link

In `src/components/Sidebar.tsx`, add a `<NavLink>` in the appropriate section.

### 6. Add any modals

Follow [Adding a new modal](#adding-a-new-modal) above.

---

## Component Conventions

### Glass cards

Use the `glass-card` CSS class for content panels:

```tsx
<div className="glass-card p-6">
  ...
</div>
```

### Buttons

```tsx
<button className="btn-primary">Primary action</button>
<button className="btn-secondary">Cancel</button>
<button className="btn-ghost">Subtle action</button>
```

### Badges

```tsx
<span className="badge badge-green">Active</span>
<span className="badge badge-red">Failed</span>
<span className="badge badge-brass">Pending</span>
<span className="badge badge-gray">Inactive</span>
<span className="badge badge-blue">In Review</span>
```

### Form inputs

```tsx
<input className="input w-full" type="text" />
<select className="input w-full">...</select>
<textarea className="input w-full resize-none" rows={3} />
```

### Loading states

```tsx
import { Loader2 } from 'lucide-react';

{isLoading && <Loader2 className="w-5 h-5 animate-spin text-slate-500" />}
```

### Error / success toasts

```ts
import { toast } from 'sonner';

toast.success('Saved successfully');
toast.error('Failed to save');
```

### Confirm before destructive action

Inline `confirm()` is acceptable for simple delete flows. For anything with user-facing consequence, use `DeleteRoutingRuleModal` as a pattern — dedicated confirm dialog with consequence text.

---

## Styling

Tailwind CSS with a custom design system. Key custom utilities (defined in `globals.css` / Tailwind config):

| Class | Usage |
|---|---|
| `glass-card` | Frosted-glass panel with border and backdrop blur |
| `btn-primary` | Brass-tinted primary action button |
| `btn-secondary` | Outlined secondary button |
| `btn-ghost` | Text-only ghost button |
| `input` | Unified form input style (text, select, textarea) |
| `badge` | Inline status chip (pair with `badge-green` etc.) |
| `data-table` | Full-width styled table |
| `text-brass-400` | Brand accent color |
| `text-2xs` | Extra-small text (10px) |

### Dark theme

The entire app uses a dark slate theme. Background is `bg-slate-900`, surfaces are `bg-slate-800` / `bg-slate-700`. Avoid hardcoded light colors.

---

## Environment Variables

All Vite environment variables must be prefixed `VITE_` to be bundled into client JS.

| Variable | Required | Description |
|---|---|---|
| `VITE_API_BASE_URL` | No | Backend URL (defaults to same-origin) |

**Security note**: Do NOT put API keys or secrets in `VITE_*` variables — they are visible in the compiled JS bundle. OCR and embedding calls go through the FastAPI backend, never directly from the browser.

---

## Document Viewer

The `<Viewer>` component (`src/features/documents/components/Viewer.tsx`) renders document pages from `ViewerPage[]` objects:

```ts
interface ViewerPage {
  id: string;
  documentId: string;
  pageNumber: number;
  width: number;
  height: number;
  thumbnailUrl?: string;   // /api/thumbnails/{doc_id} (first page)
  imageUrl?: string;       // /api/thumbnails/{doc_id}/page/{n}
  ocrText?: string;
}
```

Page thumbnails are served by the backend at:
- `GET /api/thumbnails/{document_id}` — first page JPEG
- `GET /api/thumbnails/{document_id}/page/{page_number}` — specific page JPEG (on-demand generation)

The Form Recognition page uses the per-page endpoint directly:

```tsx
<img
  src={`/api/thumbnails/${extraction.documentId}/page/${currentPage}`}
  alt={`Page ${currentPage}`}
  className="w-full object-contain"
/>
```

---

## Form Recognition Page

`src/pages/Forms.tsx` — three-tab layout:

- **Review Extraction**: side-by-side document viewer + extracted field list with per-field confidence scores and correction workflow
- **Templates**: template library management (create, activate/deactivate)
- **Processing Queue**: table of all extraction jobs with status and confidence

Key hooks (from `src/features/forms/api.ts`):

| Hook | Purpose |
|---|---|
| `useExtractionQueue()` | Paginated list of all jobs |
| `useExtraction(id)` | Detailed extraction with field values |
| `useConfirmExtraction()` | Mark extraction as accepted |
| `useReExtract()` | Re-run extraction on same document |
| `useFormTemplates()` | List all templates |
| `useCreateTemplate()` | Create a new template |

---

## Testing

```bash
cd darchiva-ui
npm run typecheck      # TypeScript — must pass before merging
npm run build          # Vite build — catches import/bundle errors
```

There are no Jest/Vitest unit tests currently. The test strategy is integration testing via Playwright (forthcoming). For now, ensure `tsc --noEmit` and `vite build` both pass.
