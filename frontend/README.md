# Grundrisse Frontend

Next.js frontend for the Grundrisse Marxist text corpus.

## Setup

```bash
# Install dependencies
npm install

# Set environment variables
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

# Run development server
npm run dev
```

The app will be available at http://localhost:3000.

## Prerequisites

The API server must be running at the URL specified in `NEXT_PUBLIC_API_URL`.
See the `api/` directory for API setup instructions.

## Pages

| Route | Description |
|-------|-------------|
| `/` | Landing page with corpus statistics |
| `/authors` | Paginated author list |
| `/authors/[id]` | Author detail with works |
| `/works/[id]` | Work reader with paragraph navigation |
| `/about` | About page |

## Development

```bash
# Run development server with hot reload
npm run dev

# Build for production
npm run build

# Run production build
npm start

# Lint code
npm run lint
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API URL |

## Tech Stack

- **Framework:** Next.js 14 (App Router)
- **Styling:** Tailwind CSS
- **Language:** TypeScript
