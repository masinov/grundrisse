import Link from 'next/link';
import type { AuthorSummary } from '@/lib/types';

interface AuthorListProps {
  authors: AuthorSummary[];
}

export default function AuthorList({ authors }: AuthorListProps) {
  return (
    <div className="divide-y divide-gray-200 border border-gray-200 rounded-lg bg-white">
      {authors.map((author) => (
        <Link
          key={author.author_id}
          href={`/authors/${author.author_id}`}
          className="flex items-center justify-between p-4 hover:bg-gray-50 transition-colors"
        >
          <div>
            <div className="font-medium text-gray-900">{author.name_canonical}</div>
            {(author.birth_year || author.death_year) && (
              <div className="text-sm text-gray-500">
                {author.birth_year || '?'}–{author.death_year || '?'}
              </div>
            )}
          </div>
          <div className="text-sm text-gray-500">{author.work_count} works</div>
        </Link>
      ))}
    </div>
  );
}
