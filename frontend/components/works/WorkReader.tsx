'use client';

import { useState } from 'react';
import type { ParagraphSummary } from '@/lib/types';
import ParagraphBlock from '@/components/reader/ParagraphBlock';
import ExtractionPanel from '@/components/reader/ExtractionPanel';

interface WorkReaderProps {
  paragraphs: ParagraphSummary[];
  hasExtractions: boolean;
}

export default function WorkReader({ paragraphs, hasExtractions }: WorkReaderProps) {
  const [selectedParagraphId, setSelectedParagraphId] = useState<string | null>(null);

  return (
    <div className="relative">
      {/* Text content */}
      <div className="prose-reader">
        {paragraphs.map((paragraph) => (
          <ParagraphBlock
            key={paragraph.paragraph_id}
            paragraph={paragraph}
            isSelected={paragraph.paragraph_id === selectedParagraphId}
            onSelect={() => {
              if (paragraph.has_extractions) {
                setSelectedParagraphId(
                  paragraph.paragraph_id === selectedParagraphId
                    ? null
                    : paragraph.paragraph_id
                );
              }
            }}
            showExtractionBadge={hasExtractions}
          />
        ))}
      </div>

      {/* Extraction panel */}
      {selectedParagraphId && (
        <ExtractionPanel
          paragraphId={selectedParagraphId}
          onClose={() => setSelectedParagraphId(null)}
        />
      )}
    </div>
  );
}
