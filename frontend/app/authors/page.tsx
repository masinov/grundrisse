import Link from 'next/link';
import { getAuthors } from '@/lib/api';
import AuthorList from '@/components/authors/AuthorList';
import AuthorSortSelect from '@/components/authors/AuthorSortSelect';

export const revalidate = 60;

interface PageProps {
  searchParams: { [key: string]: string | string[] | undefined };
}

export default async function AuthorsPage({ searchParams }: PageProps) {
  const page = Number(searchParams.page) || 1;
  const limit = 50;
  const offset = (page - 1) * limit;
  const sort = (searchParams.sort as 'name' | 'works' | 'birth_year') || 'works';
  const order = (searchParams.order as 'asc' | 'desc') || 'desc';
  const q = searchParams.q as string | undefined;

  let data = null;
  let error = null;

  try {
    data = await getAuthors({ limit, offset, sort, order, q });
  } catch (e) {
    error = e instanceof Error ? e.message : 'Failed to load authors';
  }

  const totalPages = data ? Math.ceil(data.total / limit) : 0;

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Authors</h1>
        {data && (
          <p className="text-gray-600">
            {data.total.toLocaleString()} authors in the corpus
          </p>
        )}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4 mb-6">
        <AuthorSortSelect sort={sort} order={order} q={q} />
      </div>

      {error ? (
        <div className="text-red-600 p-4 bg-red-50 rounded-lg">{error}</div>
      ) : data ? (
        <>
          <AuthorList authors={data.authors} />

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex justify-center items-center gap-4 mt-8">
              {page > 1 && (
                <Link
                  href={`/authors?page=${page - 1}&sort=${sort}&order=${order}${q ? `&q=${q}` : ''}`}
                  className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-50"
                >
                  Previous
                </Link>
              )}
              <span className="text-sm text-gray-600">
                Page {page} of {totalPages}
              </span>
              {page < totalPages && (
                <Link
                  href={`/authors?page=${page + 1}&sort=${sort}&order=${order}${q ? `&q=${q}` : ''}`}
                  className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-50"
                >
                  Next
                </Link>
              )}
            </div>
          )}
        </>
      ) : (
        <div className="text-gray-500">Loading...</div>
      )}
    </div>
  );
}
