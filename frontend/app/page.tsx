import Link from 'next/link';
import { getStats } from '@/lib/api';

export const revalidate = 60; // Revalidate every minute

export default async function HomePage() {
  let stats = null;
  try {
    stats = await getStats();
  } catch (error) {
    console.error('Failed to fetch stats:', error);
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-16 sm:py-24">
      {/* Hero */}
      <div className="text-center mb-16">
        <h1 className="text-5xl font-bold text-gray-900 mb-4">Grundrisse</h1>
        <p className="text-xl text-gray-600 mb-8">
          A digital archive of Marxist texts with AI-powered knowledge extraction
        </p>

        {stats && (
          <div className="flex justify-center gap-8 text-sm text-gray-500 mb-8">
            <div>
              <span className="block text-2xl font-bold text-gray-900">
                {stats.author_count.toLocaleString()}
              </span>
              authors
            </div>
            <div>
              <span className="block text-2xl font-bold text-gray-900">
                {stats.work_count.toLocaleString()}
              </span>
              works
            </div>
            <div>
              <span className="block text-2xl font-bold text-gray-900">
                {(stats.paragraph_count / 1_000_000).toFixed(1)}M
              </span>
              paragraphs
            </div>
          </div>
        )}

        <div className="flex justify-center gap-4">
          <Link
            href="/authors"
            className="inline-flex items-center px-6 py-3 bg-primary-600 text-white
                       font-medium rounded-lg hover:bg-primary-700 transition-colors"
          >
            Browse Authors
          </Link>
          <Link
            href="/about"
            className="inline-flex items-center px-6 py-3 border border-gray-300
                       text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
          >
            Learn More
          </Link>
        </div>
      </div>

      {/* Featured / Recently processed */}
      {stats && stats.works_with_extractions > 0 && (
        <div className="border-t border-gray-200 pt-8">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Works with AI Extractions
          </h2>
          <p className="text-gray-600 mb-4">
            {stats.works_with_extractions} work{stats.works_with_extractions !== 1 ? 's' : ''} have
            been processed with NLP to extract concepts and claims.
            {' '}
            <span className="text-gray-400">
              ({stats.extraction_coverage_percent.toFixed(2)}% coverage)
            </span>
          </p>
          <div className="bg-gray-50 rounded-lg p-4">
            <Link
              href="/works/e079fbd2-584c-5f37-bc27-246d241c62b0"
              className="block hover:bg-gray-100 rounded p-2 -m-2 transition-colors"
            >
              <div className="font-medium">The Communist Manifesto</div>
              <div className="text-sm text-gray-500">
                Karl Marx &amp; Friedrich Engels · 1848 · 1,332 claims extracted
              </div>
            </Link>
          </div>
        </div>
      )}

      {/* About section */}
      <div className="border-t border-gray-200 pt-8 mt-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">About This Project</h2>
        <p className="text-gray-600">
          Grundrisse is a research project that combines a comprehensive archive of Marxist texts
          with AI-powered knowledge extraction. Our goal is to make the intellectual history of
          Marxism navigable and searchable, enabling scholars to trace the development of concepts
          and arguments across the corpus.
        </p>
      </div>
    </div>
  );
}
