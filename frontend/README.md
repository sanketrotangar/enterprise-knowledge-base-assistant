# Enterprise Knowledge Assistant — Frontend

Minimalist, light-mode dashboard for the Enterprise Knowledge Assistant
(FastAPI + PostgreSQL/pgvector backend). Built with **React 18 + TypeScript +
Vite + Tailwind CSS + React Query + React Router**.

## Quick start

```bash
cd frontend
npm install

# start FastAPI first:  uvicorn app.main:app --reload   (port 8000)
npm run dev                 # http://localhost:5173 (proxies /api + /health to :8000)
```

Set `VITE_API_BASE_URL` in `.env.local` to point at a backend on another
origin (e.g. `http://localhost:8000`) when not using the dev proxy.

## API coverage map

| Frontend client (`src/api/`) | Backend endpoint | Status |
|---|---|---|
| `health.ts` | `GET /health` | ✅ live |
| `health.ts` | `GET /health/detailed` | ✅ live |
| `auth.ts` | `POST /api/v1/auth/login` | ✅ live |
| `auth.ts` | `GET /api/v1/auth/me` | ✅ live |
| `documents.ts` | `POST /api/v1/documents/upload` | ✅ live |
| `documents.ts` | `GET /api/v1/documents` | ✅ live |
| `documents.ts` | `GET /api/v1/documents/{id}/preview` | ✅ live |
| `documents.ts` | `PUT /api/v1/documents/{id}/roles` | ✅ live (async chunk re-copy) |
| `documents.ts` | `DELETE /api/v1/documents/{id}` | ✅ live |
| `documents.ts` | `POST /api/v1/documents/{id}/process` | ✅ live |
| `documents.ts` | `GET /api/v1/documents/{id}/status` | ✅ live |
| `search.ts` | `POST /api/v1/search` | ✅ live (answer + sources) |

Rule: **every feature whose backend phase hasn't landed shows a "Coming soon"
modal or panel** — no dead buttons, no fake data.

## Structure

```
frontend/
├── src/
│   ├── api/               # fetch clients per backend feature
│   ├── components/
│   │   ├── ui/            # primitives: Button, Card, Badge, Modal, Field…
│   │   ├── layout/        # SideBar, TopBar, AppLayout (responsive shell)
│   │   ├── documents/     # UploadModal, PreviewModal, RolesModal, StatusBadge
│   │   └── shared/        # ComingSoon panel
│   ├── features/          # cross-page hooks: auth, health polling, search
│   ├── lib/               # env, query client, formatters, status metadata
│   ├── pages/             # Login, Dashboard, Documents, Search
│   └── types/             # API contract types (mirror backend schemas)
└── vite.config.ts         # dev proxy → FastAPI :8000
```

## Design notes

- **Light mode, teal brand** — semantic color tokens in `tailwind.config.js`;
  no raw hex in components; status never communicated by color alone
  (icon/label always paired).
- **Accessible**: labeled inputs, `aria-modal` dialogs with focus trap +
  Escape/backdrop close, keyboard-navigable sidebar, visible focus rings,
  `role="status"` regions for async updates.
- **Server state via React Query** — polling with `refetchInterval` that stops
  at terminal states, retry tuned per query, no global client store needed.
- **Backend offline ≠ broken UI** — health cards show an actionable error and
  admin-backed widgets degrade to explanatory messages.
