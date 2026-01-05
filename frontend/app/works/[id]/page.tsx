import Link from 'next/link';
import { notFound } from 'next/navigation';
import { getWork, getWorkParagraphs } from '@/lib/api';
import WorkReader from '@/components/works/WorkReader';

export const revalidate = 60;

interface PageProps {
  params: { id: string };
  searchParams: { [key: string]: string | string[] | undefined };
}

export default async function WorkPage({ params, searchParams }: PageProps) {
  const page = Number(searchParams.page) || 1;
  const limit = 20;
  const offset = (page - 1) * limit;

  let work = null;
  let paragraphs = null;

  try {
    work = await getWork(params.id);
    paragraphs = await getWorkParagraphs(params.id, { limit, offset });
  } catch (error) {
    notFound();
  }

  if (!work || !paragraphs) {
    notFound();
  }

  const totalPages = Math.ceil(paragraphs.total / limit);

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Breadcrumb */}
      <div className="mb-6">
        <Link
          href={`/authors/${work.author.author_id}`}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          ← {work.author.name_canonical}
        </Link>
      </div>

      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          {work.title_canonical || work.title}
        </h1>
        <div className="flex flex-wrap items-center gap-4 text-gray-600">
          <Link
            href={`/authors/${work.author.author_id}`}
            className="hover:text-primary-600"
          >
            {work.author.name_canonical}
          </Link>
          {work.publication_year && (
            <span className="inline-flex items-center gap-2">
              <span>{work.publication_year}</span>
              {work.display_date_field && (
                <span className="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium bg-gray-100 text-gray-600 rounded">
                  {work.display_date_field === 'written_date' ? 'written' : 'published'}
                </span>
              )}
            </span>
          )}
          {work.editions[0]?.language && (
            <span>{work.editions[0].language.toUpperCase()}</span>
          )}
        </div>

        {work.source_url && (
          <div className="mt-2">
            <a
              href={work.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-gray-500 hover:text-primary-600"
            >
              Source: marxists.org ↗
            </a>
          </div>
        )}

        {work.has_extractions && work.extraction_stats && (
          <div className="mt-4 p-3 bg-primary-50 rounded-lg">
            <div className="text-sm font-medium text-primary-700 mb-1">
              ★ AI Extractions Available
            </div>
            <div className="text-sm text-primary-600">
              {work.extraction_stats.concept_mentions.toLocaleString()} concept mentions ·{' '}
              {work.extraction_stats.claims.toLocaleString()} claims extracted
            </div>
          </div>
        )}
      </div>

      {/* Reader */}
      <WorkReader
        paragraphs={paragraphs.paragraphs}
        hasExtractions={work.has_extractions}
      />

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center items-center gap-4 mt-8 pt-8 border-t border-gray-200">
          {page > 1 && (
            <Link
              href={`/works/${params.id}?page=${page - 1}`}
              className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-50"
            >
              ← Previous
            </Link>
          )}
          <span className="text-sm text-gray-600">
            Paragraphs {offset + 1}–{Math.min(offset + limit, paragraphs.total)} of{' '}
            {paragraphs.total}
          </span>
          {page < totalPages && (
            <Link
              href={`/works/${params.id}?page=${page + 1}`}
              className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-50"
            >
              Next →
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
