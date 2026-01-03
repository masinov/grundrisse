#!/usr/bin/env python3
"""
Example: Extract concepts and arguments from your own text using LLM.

This demonstrates the same pattern used in the NLP pipeline for extracting:
1. Concept mentions (technical terms, key ideas)
2. Atomic claims (arguments, assertions, theses)

Usage:
    python examples/extract_concepts_and_arguments.py
"""

import json
from anthropic import Anthropic


def render_concept_extraction_prompt(*, context: list[str], target: list[str]) -> str:
    """
    Prompt for extracting concept mentions from text.

    Similar to stage_a/prompts.py::render_a1_prompt()
    """
    return (
        "Task: Extract concept mentions from TARGET only.\n"
        "Rules:\n"
        "- CONTEXT is read-only for understanding, don't extract from it.\n"
        "- sentence_index must refer to TARGET sentence indices (0..len(TARGET)-1).\n"
        "- Only extract meaningful concepts (not common words).\n"
        "- is_technical_term: true if it's domain-specific jargon, false otherwise.\n"
        "Return ONLY a JSON object of the form:\n"
        '{"mentions":['
        '{"surface_form": "dialectical materialism", "sentence_index": 0, '
        '"is_technical_term": true, "normalized_form": null, "confidence": 0.9}'
        ']}\n\n'
        f"CONTEXT:\n{_render_sentences(context)}\n\n"
        f"TARGET:\n{_render_sentences(target)}\n"
    )


def render_argument_extraction_prompt(*, context: list[str], target: list[str]) -> str:
    """
    Prompt for extracting atomic claims (arguments) from text.

    Similar to stage_a/prompts.py::render_a3_prompt()
    """
    return (
        "Task: Extract atomic claims/arguments asserted in TARGET.\n"
        "Rules:\n"
        "- CONTEXT is read-only and must not be referenced in evidence_sentence_indices.\n"
        "- evidence_sentence_indices must be non-empty and refer only to TARGET indices.\n"
        "- claim_type: definition, thesis, empirical, normative, methodological, objection, reply.\n"
        "- polarity: assert (affirming), deny (negating), conditional.\n"
        "- modality: is, will, can, must, should, appears_as, becomes, or null.\n"
        "- Prefer fewer, higher-confidence claims; never invent evidence.\n"
        "Return ONLY a JSON object of the form:\n"
        '{"claims":['
        '{"claim_text_canonical":"Workers create surplus value", "claim_type":"thesis", '
        '"polarity":"assert", "modality":"is", "evidence_sentence_indices":[0], '
        '"about_terms":["workers", "surplus value"], "confidence":0.8}'
        ']}\n\n'
        f"CONTEXT:\n{_render_sentences(context)}\n\n"
        f"TARGET:\n{_render_sentences(target)}\n"
    )


def _render_sentences(sentences: list[str]) -> str:
    """Format sentences with indices for the prompt."""
    if not sentences:
        return "(none)"
    return "\n".join(f"[{idx}] {text}" for idx, text in enumerate(sentences))


def extract_concepts_and_arguments(text_paragraphs: list[str], api_key: str):
    """
    Extract concepts and arguments from text using Anthropic's Claude.

    Args:
        text_paragraphs: List of paragraphs (each will be split into sentences)
        api_key: Anthropic API key
    """
    client = Anthropic(api_key=api_key)

    all_results = []

    for para_idx, paragraph in enumerate(text_paragraphs):
        print(f"\n{'='*80}")
        print(f"Processing paragraph {para_idx + 1}/{len(text_paragraphs)}")
        print(f"{'='*80}")
        print(f"Text: {paragraph[:100]}...")

        # Simple sentence splitting (you could use nltk or spacy for better results)
        sentences = [s.strip() + '.' for s in paragraph.split('.') if s.strip()]

        # Build context window (use previous paragraph for context)
        context = []
        if para_idx > 0:
            prev_paragraph = text_paragraphs[para_idx - 1]
            prev_sentences = [s.strip() + '.' for s in prev_paragraph.split('.') if s.strip()]
            context = prev_sentences[-2:]  # Last 2 sentences from previous paragraph

        # Extract concepts
        print("\n1. Extracting concepts...")
        concept_prompt = render_concept_extraction_prompt(context=context, target=sentences)

        concept_response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4000,
            messages=[{"role": "user", "content": concept_prompt}]
        )

        concept_text = concept_response.content[0].text
        try:
            concepts = json.loads(concept_text)
            print(f"   Found {len(concepts.get('mentions', []))} concept mentions")
            for mention in concepts.get('mentions', []):
                print(f"   - '{mention['surface_form']}' "
                      f"(sentence {mention['sentence_index']}, "
                      f"technical={mention['is_technical_term']}, "
                      f"confidence={mention.get('confidence', 'N/A')})")
        except json.JSONDecodeError as e:
            print(f"   ⚠️  Failed to parse JSON: {e}")
            print(f"   Raw response: {concept_text[:200]}")
            concepts = {"mentions": []}

        # Extract arguments/claims
        print("\n2. Extracting arguments/claims...")
        argument_prompt = render_argument_extraction_prompt(context=context, target=sentences)

        argument_response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4000,
            messages=[{"role": "user", "content": argument_prompt}]
        )

        argument_text = argument_response.content[0].text
        try:
            arguments = json.loads(argument_text)
            print(f"   Found {len(arguments.get('claims', []))} claims")
            for claim in arguments.get('claims', []):
                print(f"   - \"{claim['claim_text_canonical']}\" "
                      f"(type={claim['claim_type']}, "
                      f"polarity={claim['polarity']}, "
                      f"confidence={claim.get('confidence', 'N/A')})")
                print(f"     Evidence: sentences {claim.get('evidence_sentence_indices', [])}")
                print(f"     About terms: {claim.get('about_terms', [])}")
        except json.JSONDecodeError as e:
            print(f"   ⚠️  Failed to parse JSON: {e}")
            print(f"   Raw response: {argument_text[:200]}")
            arguments = {"claims": []}

        # Store results
        all_results.append({
            "paragraph_index": para_idx,
            "paragraph_text": paragraph,
            "sentences": sentences,
            "concepts": concepts,
            "arguments": arguments,
            "usage": {
                "concept_tokens": concept_response.usage.input_tokens + concept_response.usage.output_tokens,
                "argument_tokens": argument_response.usage.input_tokens + argument_response.usage.output_tokens,
            }
        })

    return all_results


def main():
    """Example usage with sample Marxist text."""

    # Sample text (from Capital Vol. 1)
    sample_paragraphs = [
        "The wealth of those societies in which the capitalist mode of production "
        "prevails, presents itself as an immense accumulation of commodities. "
        "Its unit being a single commodity. Our investigation must therefore begin "
        "with the analysis of a commodity.",

        "A commodity is, in the first place, an object outside us, a thing that by "
        "its properties satisfies human wants of some sort or another. The nature "
        "of such wants, whether, for instance, they spring from the stomach or from "
        "fancy, makes no difference. Neither are we here concerned to know how the "
        "object satisfies these wants, whether directly as means of subsistence, or "
        "indirectly as means of production.",

        "Every useful thing, as iron, paper, etc., may be looked at from the two "
        "points of view of quality and quantity. It is an assemblage of many "
        "properties, and may therefore be of use in various ways. To discover the "
        "various uses of things is the work of history. So also is the establishment "
        "of socially-recognized standards of measure for the quantities of these "
        "useful objects.",
    ]

    # You'll need to set your API key
    # Get it from: https://console.anthropic.com/settings/keys
    api_key = input("Enter your Anthropic API key (or set ANTHROPIC_API_KEY env var): ").strip()

    if not api_key:
        print("Error: API key required")
        return

    print("\n" + "="*80)
    print("EXTRACTING CONCEPTS AND ARGUMENTS FROM SAMPLE TEXT")
    print("="*80)

    results = extract_concepts_and_arguments(sample_paragraphs, api_key)

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    total_concepts = sum(len(r['concepts'].get('mentions', [])) for r in results)
    total_claims = sum(len(r['arguments'].get('claims', [])) for r in results)
    total_tokens = sum(r['usage']['concept_tokens'] + r['usage']['argument_tokens'] for r in results)

    print(f"Total paragraphs processed: {len(results)}")
    print(f"Total concepts extracted: {total_concepts}")
    print(f"Total claims extracted: {total_claims}")
    print(f"Total tokens used: {total_tokens:,}")
    print(f"Estimated cost: ${total_tokens * 0.003 / 1000:.4f} (at $3/M tokens)")

    # Save results
    output_file = "extraction_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results saved to: {output_file}")


if __name__ == "__main__":
    main()
