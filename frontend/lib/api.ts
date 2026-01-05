/**
 * API client for the Grundrisse backend.
 */

import type {
  AuthorDetail,
  AuthorListResponse,
  ParagraphExtractions,
  SearchResponse,
  Stats,
  WorkDetail,
  WorkParagraphsResponse,
} from './types';

const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
// When running inside Docker, server-side requests must use the service DNS name (e.g. http://api:8000),
// while browser requests should use a host-resolvable URL (e.g. http://localhost:8000).
const INTERNAL_API_URL = process.env.API_URL_INTERNAL || process.env.INTERNAL_API_URL || 'http://api:8000';

function getApiBaseUrl(): string {
  return typeof window === 'undefined' ? INTERNAL_API_URL : PUBLIC_API_URL;
}

/**
 * Fetch wrapper with error handling.
 */
async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${getApiBaseUrl()}${path}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!response.ok) {
    let bodyText = '';
    try {
      bodyText = await response.text();
    } catch {
      bodyText = '';
    }
    throw new Error(`API error: ${response.status} ${response.statusText}${bodyText ? ` — ${bodyText}` : ''}`);
  }

  return response.json();
}

/**
 * Get corpus statistics.
 */
export async function getStats(): Promise<Stats> {
  return fetchApi<Stats>('/api/stats');
}

/**
 * List authors with pagination.
 */
export async function getAuthors(params?: {
  limit?: number;
  offset?: number;
  sort?: 'name' | 'works' | 'birth_year';
  order?: 'asc' | 'desc';
  q?: string;
}): Promise<AuthorListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set('limit', params.limit.toString());
  if (params?.offset) searchParams.set('offset', params.offset.toString());
  if (params?.sort) searchParams.set('sort', params.sort);
  if (params?.order) searchParams.set('order', params.order);
  if (params?.q) searchParams.set('q', params.q);

  const query = searchParams.toString();
  return fetchApi<AuthorListResponse>(`/api/authors${query ? `?${query}` : ''}`);
}

/**
 * Get author detail with works.
 */
export async function getAuthor(authorId: string): Promise<AuthorDetail> {
  return fetchApi<AuthorDetail>(`/api/authors/${authorId}`);
}

/**
 * Get work detail.
 */
export async function getWork(workId: string): Promise<WorkDetail> {
  return fetchApi<WorkDetail>(`/api/works/${workId}`);
}

/**
 * Get paragraphs for a work.
 */
export async function getWorkParagraphs(
  workId: string,
  params?: {
    edition_id?: string;
    limit?: number;
    offset?: number;
  }
): Promise<WorkParagraphsResponse> {
  const searchParams = new URLSearchParams();
  if (params?.edition_id) searchParams.set('edition_id', params.edition_id);
  if (params?.limit) searchParams.set('limit', params.limit.toString());
  if (params?.offset) searchParams.set('offset', params.offset.toString());

  const query = searchParams.toString();
  return fetchApi<WorkParagraphsResponse>(
    `/api/works/${workId}/paragraphs${query ? `?${query}` : ''}`
  );
}

/**
 * Get extractions for a paragraph.
 */
export async function getParagraphExtractions(
  paragraphId: string
): Promise<ParagraphExtractions> {
  return fetchApi<ParagraphExtractions>(`/api/paragraphs/${paragraphId}/extractions`);
}

/**
 * Search authors and works.
 */
export async function search(
  query: string,
  params?: {
    type?: 'all' | 'authors' | 'works';
    limit?: number;
  }
): Promise<SearchResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set('q', query);
  if (params?.type) searchParams.set('type', params.type);
  if (params?.limit) searchParams.set('limit', params.limit.toString());

  return fetchApi<SearchResponse>(`/api/search?${searchParams.toString()}`);
}
