/**
 * TypeScript interfaces matching the API responses.
 */

// Stats
export interface Stats {
  author_count: number;
  work_count: number;
  paragraph_count: number;
  works_with_extractions: number;
  extraction_coverage_percent: number;
}

// Authors
export interface AuthorSummary {
  author_id: string;
  name_canonical: string;
  birth_year: number | null;
  death_year: number | null;
  work_count: number;
}

export interface AuthorListResponse {
  total: number;
  limit: number;
  offset: number;
  authors: AuthorSummary[];
}

export interface WorkSummary {
  work_id: string;
  title: string;
  title_canonical: string | null;
  publication_year: number | null;
  date_confidence: string | null;
  language: string | null;
  paragraph_count: number;
  has_extractions: boolean;
}

export interface AuthorDetail {
  author_id: string;
  name_canonical: string;
  birth_year: number | null;
  death_year: number | null;
  aliases: string[];
  work_count: number;
  works: WorkSummary[];
}

// Works
export interface WorkListItem {
  work_id: string;
  title: string;
  author_id: string;
  author_name: string;
  publication_year: number | null;
  date_confidence: string | null;
  language: string | null;
  paragraph_count: number;
  has_extractions: boolean;
}

export interface WorkListResponse {
  total: number;
  limit: number;
  offset: number;
  works: WorkListItem[];
}

export interface EditionInfo {
  edition_id: string;
  language: string | null;
  source_url: string | null;
  paragraph_count: number;
}

export interface AuthorInfo {
  author_id: string;
  name_canonical: string;
}

export interface ExtractionStats {
  paragraphs_processed: number;
  concept_mentions: number;
  claims: number;
}

export interface WorkDetail {
  work_id: string;
  title: string;
  title_canonical: string | null;
  author: AuthorInfo;
  publication_year: number | null;
  date_confidence: string | null;
  source_url: string | null;
  editions: EditionInfo[];
  has_extractions: boolean;
  extraction_stats: ExtractionStats | null;
}

// Paragraphs
export interface ParagraphSummary {
  paragraph_id: string;
  order_in_edition: number;
  text_content: string;
  has_extractions: boolean;
  concept_count: number;
  claim_count: number;
}

export interface WorkParagraphsResponse {
  work_id: string;
  edition_id: string;
  total: number;
  limit: number;
  offset: number;
  paragraphs: ParagraphSummary[];
}

// Extractions
export interface ConceptMention {
  mention_id: string;
  text: string;
  char_start: number | null;
  char_end: number | null;
}

export interface Claim {
  claim_id: string;
  text: string;
  confidence: number | null;
}

export interface ParagraphExtractions {
  paragraph_id: string;
  concepts: ConceptMention[];
  claims: Claim[];
}

// Search
export interface AuthorSearchResult {
  author_id: string;
  name_canonical: string;
  work_count: number;
}

export interface WorkSearchResult {
  work_id: string;
  title: string;
  author_name: string;
  publication_year: number | null;
}

export interface SearchResponse {
  query: string;
  authors: AuthorSearchResult[];
  works: WorkSearchResult[];
}
