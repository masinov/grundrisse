'use client';

import { useEffect, useState } from 'react';
import { getParagraphExtractions } from '@/lib/api';
import type { ParagraphExtractions } from '@/lib/types';

interface ExtractionPanelProps {
  paragraphId: string;
  onClose: () => void;
}

export default function ExtractionPanel({ paragraphId, onClose }: ExtractionPanelProps) {
  const [extractions, setExtractions] = useState<ParagraphExtractions | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const data = await getParagraphExtractions(paragraphId);
        if (!cancelled) {
          setExtractions(data);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load extractions');
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [paragraphId]);

  return (
    <div className="fixed inset-y-0 right-0 w-80 bg-white border-l border-gray-200 shadow-lg z-40 overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 bg-white border-b border-gray-200 p-4 flex items-center justify-between">
        <h3 className="font-semibold text-gray-900">Extractions</h3>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 transition-colors"
          title="Close"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="p-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="w-6 h-6 border-2 border-gray-300 border-t-primary-500 rounded-full animate-spin" />
          </div>
        ) : error ? (
          <div className="text-red-600 text-sm">{error}</div>
        ) : extractions ? (
          <div className="space-y-6">
            {/* Concepts */}
            {extractions.concepts.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-gray-500 uppercase mb-2">
                  Concepts ({extractions.concepts.length})
                </h4>
                <ul className="space-y-1">
                  {extractions.concepts.map((concept) => (
                    <li
                      key={concept.mention_id}
                      className="text-sm text-gray-700 py-1 px-2 bg-gray-50 rounded"
                    >
                      {concept.text}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Claims */}
            {extractions.claims.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-gray-500 uppercase mb-2">
                  Claims ({extractions.claims.length})
                </h4>
                <ul className="space-y-2">
                  {extractions.claims.map((claim) => (
                    <li
                      key={claim.claim_id}
                      className="text-sm text-gray-700 py-2 px-2 bg-gray-50 rounded"
                    >
                      <p className="italic">&ldquo;{claim.text}&rdquo;</p>
                      {claim.confidence !== null && (
                        <p className="text-xs text-gray-400 mt-1">
                          Confidence: {(claim.confidence * 100).toFixed(0)}%
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {extractions.concepts.length === 0 && extractions.claims.length === 0 && (
              <p className="text-sm text-gray-500">No extractions for this paragraph.</p>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
