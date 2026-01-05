'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { search } from '@/lib/api';
import type { SearchResponse } from '@/lib/types';

export default function SearchInput() {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Debounced search
  useEffect(() => {
    if (query.length < 2) {
      setResults(null);
      return;
    }

    const timer = setTimeout(async () => {
      setIsLoading(true);
      try {
        const data = await search(query, { limit: 10 });
        setResults(data);
        setIsOpen(true);
      } catch (error) {
        console.error('Search failed:', error);
      } finally {
        setIsLoading(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [query]);

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        !inputRef.current?.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelect = useCallback(
    (type: 'author' | 'work', id: string) => {
      setIsOpen(false);
      setQuery('');
      if (type === 'author') {
        router.push(`/authors/${id}`);
      } else {
        router.push(`/works/${id}`);
      }
    },
    [router]
  );

  return (
    <div className="relative">
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results && setIsOpen(true)}
        placeholder="Search authors, works..."
        className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md
                   focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
      />

      {isLoading && (
        <div className="absolute right-3 top-1/2 -translate-y-1/2">
          <div className="w-4 h-4 border-2 border-gray-300 border-t-primary-500 rounded-full animate-spin" />
        </div>
      )}

      {isOpen && results && (results.authors.length > 0 || results.works.length > 0) && (
        <div
          ref={dropdownRef}
          className="absolute top-full left-0 right-0 mt-1 bg-white border border-gray-200
                     rounded-md shadow-lg z-50 max-h-96 overflow-y-auto"
        >
          {results.authors.length > 0 && (
            <div className="p-2">
              <div className="text-xs font-semibold text-gray-400 uppercase px-2 mb-1">
                Authors
              </div>
              {results.authors.map((author) => (
                <button
                  key={author.author_id}
                  onClick={() => handleSelect('author', author.author_id)}
                  className="w-full text-left px-2 py-1.5 text-sm hover:bg-gray-100 rounded"
                >
                  <span className="font-medium">{author.name_canonical}</span>
                  <span className="text-gray-400 ml-2">{author.work_count} works</span>
                </button>
              ))}
            </div>
          )}

          {results.works.length > 0 && (
            <div className="p-2 border-t border-gray-100">
              <div className="text-xs font-semibold text-gray-400 uppercase px-2 mb-1">
                Works
              </div>
              {results.works.map((work) => (
                <button
                  key={work.work_id}
                  onClick={() => handleSelect('work', work.work_id)}
                  className="w-full text-left px-2 py-1.5 text-sm hover:bg-gray-100 rounded"
                >
                  <div className="font-medium truncate">{work.title}</div>
                  <div className="text-gray-400 text-xs">
                    {work.author_name}
                    {work.publication_year && ` · ${work.publication_year}`}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
