# Frontend Development Plan

> MVP: A corpus reader that enables browsing and reading the 19,098 works currently ingested, with extraction display where available.

## Goals

1. **Immediately useful**: Read the entire marxists.org corpus in a proper interface
2. **Honest UI**: Show extractions where they exist, don't pretend elsewhere
3. **Shareable**: Every view has a stable URL for collaboration
4. **Extensible**: Architecture supports future features (RAG, graphs, collaboration)

## Architecture Decisions

### Monorepo Structure

Frontend and API live in the same repository as existing services:

```
grundrisse/
├── packages/core/              # Existing: SQLAlchemy models, Alembic migrations
├── pipelines/nlp_pipeline/     # Existing: Stage A, Stage B
├── services/ingest_service/    # Existing: crawl, ingest, metadata CLI
│
├── api/                        # NEW: FastAPI backend for frontend
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── src/api/
│       ├── __init__.py
│       ├── main.py             # FastAPI app, CORS, lifespan
│       ├── config.py           # Settings from environment
│       ├── deps.py             # Database session dependency
│       └── routes/
│           ├── __init__.py
│           ├── authors.py
│           ├── works.py
│           ├── paragraphs.py
│           └── search.py
│
├── frontend/                   # NEW: Next.js application
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.js
│   ├── tailwind.config.js
│   ├── Dockerfile
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx            # Landing/home
│   │   ├── authors/
│   │   │   ├── page.tsx        # Author index
│   │   │   └── [id]/
│   │   │       └── page.tsx    # Author detail
│   │   ├── works/
│   │   │   └── [id]/
│   │   │       └── page.tsx    # Work reader
│   │   └── about/
│   │       └── page.tsx
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Header.tsx
│   │   │   ├── Footer.tsx
│   │   │   └── Container.tsx
│   │   ├── authors/
│   │   │   ├── AuthorList.tsx
│   │   │   └── AuthorCard.tsx
│   │   ├── works/
│   │   │   ├── WorkList.tsx
│   │   │   ├── WorkCard.tsx
│   │   │   └── WorkReader.tsx
│   │   ├── reader/
│   │   │   ├── ParagraphBlock.tsx
│   │   │   └── ExtractionPanel.tsx
│   │   └── search/
│   │       ├── SearchInput.tsx
│   │       └── SearchResults.tsx
│   ├── lib/
│   │   ├── api.ts              # API client functions
│   │   └── types.ts            # TypeScript interfaces
│   └── public/
│
└── docker-compose.yml          # Updated with api + frontend services
```

### Tech Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| Frontend framework | Next.js 14+ (App Router) | Server components, file-based routing, good DX |
| Styling | Tailwind CSS | Rapid iteration, consistent design system |
| API framework | FastAPI | Already familiar, auto OpenAPI docs, async support |
| Database | PostgreSQL (existing) | No changes needed |
| ORM | SQLAlchemy (existing models) | Reuse `grundrisse-core` package |
| Deployment | Docker Compose (dev), Vercel/Docker (prod) | Flexible |

### Why Separate API Service

| `ingest_service` | `api/` |
|------------------|--------|
| CLI batch tools | HTTP request/response |
| Write-heavy (ingest, extract) | Read-heavy (serve pages) |
| Long-running jobs | Fast queries (<100ms) |
| Internal tooling | Public-facing |

Both import from `packages/core` for shared models.

---

## Phase 1: MVP Reader

### Scope

Three pages + global search:

1. **`/authors`** — Paginated author list with work counts
2. **`/authors/[id]`** — Author detail with works list
3. **`/works/[id]`** — Full text reader with paragraph navigation
4. **Global search** — Authors and work titles

### Out of Scope (Phase 1)

- User accounts / authentication
- Semantic search (requires embeddings)
- Concept/claim pages (requires Stage B canonicalization)
- Timeline visualization
- RAG / Ask interface
- Collaboration features

---

## API Specification

### Base URL

```
Development: http://localhost:8000/api
Production:  https://api.grundrisse.org/api  (example)
```

### Endpoints

#### Authors

```
GET /api/authors
  Query params:
    - limit: int (default 50, max 200)
    - offset: int (default 0)
    - sort: "name" | "works" | "birth_year" (default "works")
    - order: "asc" | "desc" (default "desc")
    - q: string (optional, filter by name)

  Response:
    {
      "total": 1333,
      "limit": 50,
      "offset": 0,
      "authors": [
        {
          "author_id": "uuid",
          "name_canonical": "Karl Marx",
          "birth_year": 1818,
          "death_year": 1883,
          "work_count": 47
        },
        ...
      ]
    }
```

```
GET /api/authors/{author_id}
  Response:
    {
      "author_id": "uuid",
      "name_canonical": "Karl Marx",
      "birth_year": 1818,
      "death_year": 1883,
      "aliases": ["Karl Heinrich Marx"],
      "work_count": 47,
      "works": [
        {
          "work_id": "uuid",
          "title": "The Communist Manifesto",
          "title_canonical": "The Communist Manifesto",
          "publication_year": 1848,
          "date_confidence": "heuristic",
          "language": "en",
          "paragraph_count": 360,
          "has_extractions": true
        },
        ...
      ]
    }
```

#### Works

```
GET /api/works
  Query params:
    - limit: int (default 50, max 200)
    - offset: int (default 0)
    - author_id: uuid (optional)
    - year_min: int (optional)
    - year_max: int (optional)
    - language: string (optional)
    - has_extractions: bool (optional)
    - q: string (optional, filter by title)

  Response:
    {
      "total": 19098,
      "limit": 50,
      "offset": 0,
      "works": [
        {
          "work_id": "uuid",
          "title": "The Communist Manifesto",
          "author_id": "uuid",
          "author_name": "Karl Marx",
          "publication_year": 1848,
          "date_confidence": "heuristic",
          "language": "en",
          "paragraph_count": 360,
          "has_extractions": true
        },
        ...
      ]
    }
```

```
GET /api/works/{work_id}
  Response:
    {
      "work_id": "uuid",
      "title": "The Communist Manifesto",
      "title_canonical": "The Communist Manifesto",
      "author": {
        "author_id": "uuid",
        "name_canonical": "Karl Marx"
      },
      "publication_year": 1848,
      "date_confidence": "heuristic",
      "source_url": "https://marxists.org/...",
      "editions": [
        {
          "edition_id": "uuid",
          "language": "en",
          "source_url": "https://...",
          "paragraph_count": 360
        }
      ],
      "has_extractions": true,
      "extraction_stats": {
        "paragraphs_processed": 305,
        "concept_mentions": 1690,
        "claims": 1332
      }
    }
```

#### Paragraphs

```
GET /api/works/{work_id}/paragraphs
  Query params:
    - edition_id: uuid (optional, defaults to first edition)
    - limit: int (default 20, max 100)
    - offset: int (default 0)

  Response:
    {
      "work_id": "uuid",
      "edition_id": "uuid",
      "total": 360,
      "limit": 20,
      "offset": 0,
      "paragraphs": [
        {
          "paragraph_id": "uuid",
          "order_in_edition": 1,
          "text_content": "A spectre is haunting Europe...",
          "has_extractions": true,
          "concept_count": 5,
          "claim_count": 3
        },
        ...
      ]
    }
```

```
GET /api/paragraphs/{paragraph_id}/extractions
  Response:
    {
      "paragraph_id": "uuid",
      "concepts": [
        {
          "mention_id": "uuid",
          "text": "class struggle",
          "char_start": 45,
          "char_end": 59
        },
        ...
      ],
      "claims": [
        {
          "claim_id": "uuid",
          "text": "The history of all hitherto existing society is the history of class struggles",
          "confidence": 0.92
        },
        ...
      ]
    }
```

#### Search

```
GET /api/search
  Query params:
    - q: string (required, min 2 chars)
    - type: "all" | "authors" | "works" (default "all")
    - limit: int (default 20)

  Response:
    {
      "query": "marx capital",
      "authors": [
        {
          "author_id": "uuid",
          "name_canonical": "Karl Marx",
          "work_count": 47
        }
      ],
      "works": [
        {
          "work_id": "uuid",
          "title": "Capital, Volume I",
          "author_name": "Karl Marx",
          "publication_year": 1867
        },
        ...
      ]
    }
```

#### Stats (for landing page)

```
GET /api/stats
  Response:
    {
      "author_count": 1333,
      "work_count": 19098,
      "paragraph_count": 1763385,
      "works_with_extractions": 1,
      "extraction_coverage_percent": 0.005
    }
```

---

## Page Specifications

### Landing Page (`/`)

Simple entry point:

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                         GRUNDRISSE                              │
│                                                                 │
│            A digital archive of Marxist texts                   │
│                                                                 │
│         1,333 authors  ·  19,098 works  ·  1.7M paragraphs     │
│                                                                 │
│                    ┌─────────────────────┐                      │
│                    │  Search authors,    │                      │
│                    │  works, concepts... │                      │
│                    └─────────────────────┘                      │
│                                                                 │
│              [Browse Authors]  [Browse Works]                   │
│                                                                 │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  Recently processed:                                            │
│  • The Communist Manifesto (1,332 claims extracted)            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Author Index (`/authors`)

```
┌─────────────────────────────────────────────────────────────────┐
│  Grundrisse                              [Search...]    [About] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Authors                                                        │
│  1,333 authors · 19,098 works                                  │
│                                                                 │
│  [Sort: Most works ▼]  [Search authors...]                     │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  Karl Marx                                       47 works │ │
│  │  1818–1883                                                │ │
│  ├───────────────────────────────────────────────────────────┤ │
│  │  Vladimir Lenin                                 892 works │ │
│  │  1870–1924                                                │ │
│  ├───────────────────────────────────────────────────────────┤ │
│  │  Friedrich Engels                                89 works │ │
│  │  1820–1895                                                │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  Showing 1-50 of 1,333          [← Previous]  [Next →]         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Author Detail (`/authors/[id]`)

```
┌─────────────────────────────────────────────────────────────────┐
│  Grundrisse                              [Search...]    [About] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ← All Authors                                                  │
│                                                                 │
│  KARL MARX                                                      │
│  1818–1883 · 47 works                                          │
│  Also known as: Karl Heinrich Marx                              │
│                                                                 │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  Works                               [Sort: Year ▼] [Filter]   │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  1844 · Economic and Philosophic Manuscripts              │ │
│  │         23 paragraphs · English                  [Read →] │ │
│  ├───────────────────────────────────────────────────────────┤ │
│  │  1848 · The Communist Manifesto                      ★    │ │
│  │         360 paragraphs · English                 [Read →] │ │
│  │         1,332 claims · 1,690 concepts extracted           │ │
│  ├───────────────────────────────────────────────────────────┤ │
│  │  1867 · Capital, Volume I                                 │ │
│  │         1,247 paragraphs · English               [Read →] │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ★ NLP extractions available                                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Work Reader (`/works/[id]`)

```
┌─────────────────────────────────────────────────────────────────┐
│  Grundrisse                              [Search...]    [About] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ← Karl Marx                                                    │
│                                                                 │
│  THE COMMUNIST MANIFESTO                                        │
│  Karl Marx & Friedrich Engels · 1848 · English                 │
│  Source: marxists.org                                 [Visit ↗] │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                                                         │   │
│  │  ¶1                                            [5c 3cl] │   │
│  │  A spectre is haunting Europe — the spectre of         │   │
│  │  communism. All the powers of old Europe have entered  │   │
│  │  into a holy alliance to exorcise this spectre: Pope   │   │
│  │  and Tsar, Metternich and Guizot, French Radicals and │   │
│  │  German police-spies.                                  │   │
│  │                                                         │   │
│  │  ───────────────────────────────────────────────────   │   │
│  │                                                         │   │
│  │  ¶2                                            [4c 2cl] │   │
│  │  The history of all hitherto existing society is the   │   │
│  │  history of class struggles.                           │   │
│  │                                                         │   │
│  │  Freeman and slave, patrician and plebeian, lord and   │   │
│  │  serf, guild-master and journeyman, in a word,         │   │
│  │  oppressor and oppressed, stood in constant opposition │   │
│  │  to one another...                                     │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Paragraphs 1-20 of 360              [← Previous]  [Next →]    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

[5c 3cl] = 5 concepts, 3 claims (clickable to show extraction panel)
```

### Extraction Panel (slide-out on click)

```
┌────────────────────────────────┐
│  Paragraph 2 · Extractions     │  ← Click [5c 3cl] badge
├────────────────────────────────┤
│                                │
│  CONCEPTS (5)                  │
│  ─────────────────────────     │
│  • class struggle              │
│  • society                     │
│  • history                     │
│  • oppressor                   │
│  • oppressed                   │
│                                │
│  CLAIMS (3)                    │
│  ─────────────────────────     │
│  • "The history of all         │
│     hitherto existing society  │
│     is the history of class    │
│     struggles"                 │
│                                │
│  • "Oppressor and oppressed    │
│     stood in constant          │
│     opposition"                │
│                                │
│  • "Fight ended in             │
│     revolutionary              │
│     reconstitution or          │
│     common ruin"               │
│                                │
│                       [Close]  │
└────────────────────────────────┘
```

---

## Development Phases

### Phase 1: MVP Reader (Weeks 1-6)

#### Week 1-2: Foundation
- [ ] Create `api/` package structure
- [ ] Implement FastAPI app with CORS, health check
- [ ] Implement `/api/authors` endpoint
- [ ] Implement `/api/authors/{id}` endpoint
- [ ] Create `frontend/` with Next.js + Tailwind
- [ ] Implement `/authors` page
- [ ] Implement `/authors/[id]` page

#### Week 3-4: Reader
- [ ] Implement `/api/works/{id}` endpoint
- [ ] Implement `/api/works/{id}/paragraphs` endpoint
- [ ] Implement `/api/paragraphs/{id}/extractions` endpoint
- [ ] Implement `/works/[id]` reader page
- [ ] Add paragraph pagination
- [ ] Add extraction badges and panel

#### Week 5-6: Polish
- [ ] Implement `/api/search` endpoint
- [ ] Add global search UI
- [ ] Implement landing page with stats
- [ ] Add About page
- [ ] Responsive design pass
- [ ] Error handling and loading states
- [ ] Docker Compose integration

### Phase 2: Enhanced Navigation (Future)

- [ ] Author page timeline visualization
- [ ] Date range filters
- [ ] Language filters
- [ ] "By Tradition" grouping (requires classification data)
- [ ] Keyboard navigation for reader

### Phase 3: Knowledge Features (Future)

- [ ] Concept pages (requires Stage B canonicalization)
- [ ] Claim pages
- [ ] Concept highlighting in reader
- [ ] "Related passages" (requires embeddings)

### Phase 4: Research Tools (Future)

- [ ] Semantic search
- [ ] Ask/RAG interface
- [ ] Saved searches
- [ ] Export citations

### Phase 5: Collaboration (Future)

- [ ] User accounts
- [ ] Reading lists
- [ ] Annotations
- [ ] Community curation

---

## Setup Instructions

### Prerequisites

- Node.js 18+
- Python 3.11+
- Docker & Docker Compose
- PostgreSQL running with data loaded

### API Setup

```bash
# From repo root
cd api

# Create virtual environment (or use uv)
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -e ".[dev]"

# Set environment variables
export DATABASE_URL="postgresql://user:pass@localhost:5432/grundrisse"

# Run development server
uvicorn api.main:app --reload --port 8000

# API docs available at http://localhost:8000/docs
```

### Frontend Setup

```bash
# From repo root
cd frontend

# Install dependencies
npm install

# Set environment variables
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

# Run development server
npm run dev

# App available at http://localhost:3000
```

### Docker Compose (Full Stack)

```bash
# From repo root
docker compose up -d db        # Start database
docker compose up api frontend # Start API and frontend

# Or all together:
docker compose up
```

---

## Environment Variables

### API (`api/.env`)

```
DATABASE_URL=postgresql://user:pass@localhost:5432/grundrisse
CORS_ORIGINS=http://localhost:3000,https://grundrisse.org
```

### Frontend (`frontend/.env.local`)

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Testing Strategy

### API

```bash
cd api
pytest tests/ -v
```

- Unit tests for query logic
- Integration tests for endpoints (using test database)

### Frontend

```bash
cd frontend
npm run test        # Unit tests (Vitest or Jest)
npm run e2e         # E2E tests (Playwright)
```

- Component tests for key UI elements
- E2E tests for critical user flows (browse → read)

---

## Performance Considerations

### API

- Add database indexes for common queries:
  ```sql
  CREATE INDEX ix_work_author_id ON work(author_id);
  CREATE INDEX ix_work_publication_year ON work((publication_date->>'year'));
  CREATE INDEX ix_paragraph_edition_order ON paragraph(edition_id, order_in_edition);
  ```
- Paginate all list endpoints (never return unbounded results)
- Consider materialized views for author work counts

### Frontend

- Use Next.js Server Components for initial data fetching
- Lazy load extraction panel (only fetch when clicked)
- Virtual scrolling for very long works (1000+ paragraphs)
- Image optimization (if any images added later)

---

## Open Questions

1. **Domain/hosting**: Where will this be deployed? Vercel? Self-hosted?
2. **Analytics**: Do we want usage tracking? Privacy considerations?
3. **Internationalization**: UI in multiple languages from start, or English-only MVP?
4. **Mobile**: Full responsive design, or desktop-first for MVP?
5. **Offline**: Any PWA/offline reading requirements?

---

## References

- [Next.js App Router Documentation](https://nextjs.org/docs/app)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Tailwind CSS](https://tailwindcss.com/docs)
- [Existing Database Schema](../packages/core/src/grundrisse_core/db/models.py)
