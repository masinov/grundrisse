'use client';

import { useRouter } from 'next/navigation';

export default function AuthorSortSelect(props: {
  sort: 'name' | 'works' | 'birth_year';
  order: 'asc' | 'desc';
  q?: string;
}) {
  const router = useRouter();
  const { sort, order, q } = props;

  return (
    <div className="flex items-center gap-2">
      <label className="text-sm text-gray-600">Sort by:</label>
      <select
        defaultValue={`${sort}-${order}`}
        onChange={(e) => {
          const [newSort, newOrder] = e.target.value.split('-');
          const params = new URLSearchParams();
          params.set('sort', newSort);
          params.set('order', newOrder);
          if (q) params.set('q', q);
          router.push(`/authors?${params.toString()}`);
        }}
        className="border border-gray-300 rounded px-2 py-1 text-sm"
      >
        <option value="works-desc">Most works</option>
        <option value="works-asc">Fewest works</option>
        <option value="name-asc">Name (A-Z)</option>
        <option value="name-desc">Name (Z-A)</option>
        <option value="birth_year-asc">Birth year (earliest)</option>
        <option value="birth_year-desc">Birth year (latest)</option>
      </select>
    </div>
  );
}

