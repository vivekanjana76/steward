# Steward Dashboard

The maintainer's **command center** — "what Steward did this week." A dark,
glassmorphic Next.js (App Router) + Tailwind UI over the Steward API
([`src/steward/api/`](../src/steward/api/)):

- **Activity Stream** — the append-only, hash-chained audit log: every action
  Steward proposed, dry-ran, executed, or was refused, colour-coded by policy
  verdict, with trace + chain anchors.
- **Approval Queue** — pending greylist actions with **Approve / Reject**
  controls that route through the policy approval queue (never a direct
  mutation), audited as `human:<login>`.
- **Eval Scorecard** — published metrics, or an honest "not yet measured" state
  until the eval harness (M6) writes a report.
- **Stat rail** — pending approvals, records, dry-run share, blacklist denials.

The UI **degrades gracefully**: if the API is unreachable it renders an honest
"core offline" state instead of crashing.

## Run it

The dashboard reads from the Steward API, so start that first:

```bash
# from the repo root — seed a slice of real policy decisions so it's non-empty
STEWARD_GITHUB_REPO=owner/repo STEWARD_SEED_DEMO=true just api
```

Then, in `dashboard/`:

```bash
npm install
cp .env.example .env.local   # NEXT_PUBLIC_STEWARD_API=http://localhost:8000
npm run dev                  # http://localhost:3000
```

The API allows CORS from `http://localhost:3000` in dev, so approve/reject work
from the browser. Server-side rendering reads the API directly.

## Checks

```bash
npm run typecheck   # tsc --noEmit
npm run build       # next build (runs ESLint)
```

## Design notes

- **Stack:** Next.js 15, React 19, Tailwind v4, framer-motion. Typed props, no
  `any`, explicit server/client boundaries (CLAUDE.md §13).
- The response types in [`src/lib/types.ts`](src/lib/types.ts) mirror the API's
  Pydantic schemas — keep them in sync.
- The page is `force-dynamic`: the audit log and queue are live state, never
  cached.
- Verdict colours (emerald = allow, amber = approval, rose = deny) match the API
  so the UI and the audit log speak the same language.
