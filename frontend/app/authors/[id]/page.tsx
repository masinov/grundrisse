import Link from 'next/link';
import { notFound } from 'next/navigation';
import { getAuthor } from '@/lib/api';

export const revalidate = 60;

interface PageProps {
  params: { id: string };
}

export default async function AuthorPage({ params }: PageProps) {
  let author = null;
  try {
    author = await getAuthor(params.id);
  } catch (error) {
    notFound();
  }

  if (!author) {
    notFound();
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      {/* Breadcrumb */}
      <div className="mb-6">
        <Link href="/authors" className="text-sm text-gray-500 hover:text-gray-700">
          ← All Authors
        </Link>
      </div>

      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">{author.name_canonical}</h1>
        <div className="flex items-center gap-4 text-gray-600">
          {(author.birth_year || author.death_year) && (
            <span>
              {author.birth_year || '?'}–{author.death_year || '?'}
            </span>
          )}
          <span>{author.work_count} works</span>
        </div>
        {author.aliases.length > 0 && (
          <div className="mt-2 text-sm text-gray-500">
            Also known as: {author.aliases.join(', ')}
          </div>
        )}
      </div>

      {/* Works */}
      <div>
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Works</h2>
        <div className="divide-y divide-gray-200 border border-gray-200 rounded-lg bg-white">
          {author.works.map((work) => (
            <Link
              key={work.work_id}
              href={`/works/${work.work_id}`}
              className="block p-4 hover:bg-gray-50 transition-colors"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    {work.publication_year && (
                      <span className="text-sm font-mono text-gray-400">
                        {work.publication_year}
                      </span>
                    )}
                    <span className="font-medium text-gray-900">{work.title}</span>
                    {work.has_extractions && (
                      <span className="inline-flex items-center px-1.5 py-0.5 text-xs font-medium bg-primary-50 text-primary-700 rounded">
                        ★ Extracted
                      </span>
                    )}
                  </div>
                  <div className="mt-1 text-sm text-gray-500">
                    {work.paragraph_count} paragraphs
                    {work.language && ` · ${work.language.toUpperCase()}`}
                  </div>
                </div>
                <span className="text-gray-400">→</span>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
