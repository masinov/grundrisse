import type { ParagraphSummary } from '@/lib/types';

interface ParagraphBlockProps {
  paragraph: ParagraphSummary;
  isSelected: boolean;
  onSelect: () => void;
  showExtractionBadge: boolean;
}

export default function ParagraphBlock({
  paragraph,
  isSelected,
  onSelect,
  showExtractionBadge,
}: ParagraphBlockProps) {
  const hasExtractions = paragraph.has_extractions;

  return (
    <div
      className={`relative group py-2 -mx-4 px-4 rounded transition-colors ${
        isSelected ? 'bg-primary-50' : hasExtractions ? 'hover:bg-gray-50' : ''
      }`}
    >
      {/* Paragraph number */}
      <span className="absolute left-0 top-2 text-xs text-gray-300 font-mono w-8 text-right">
        ¶{paragraph.order_in_edition}
      </span>

      {/* Text content */}
      <div className="pl-6">
        <p className="text-gray-800 leading-relaxed">{paragraph.text_content}</p>
      </div>

      {/* Extraction badge */}
      {showExtractionBadge && hasExtractions && (
        <button
          onClick={onSelect}
          className={`absolute right-0 top-2 extraction-badge ${
            hasExtractions ? 'has-extractions' : ''
          }`}
          title="View concepts and claims"
        >
          <span>{paragraph.concept_count}c</span>
          <span>{paragraph.claim_count}cl</span>
        </button>
      )}
    </div>
  );
}
