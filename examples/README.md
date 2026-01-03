# Examples: Extracting Concepts and Arguments with LLMs

This directory contains examples of how to use the Grundrisse extraction patterns with your own text.

## Quick Start

### 1. Extract from Sample Text

```bash
# Install dependencies
pip install anthropic

# Run the example
python examples/extract_concepts_and_arguments.py
```

You'll be prompted for your Anthropic API key. Get one at: https://console.anthropic.com/settings/keys

### 2. Extract from Your Own Text

Edit `extract_concepts_and_arguments.py` and replace `sample_paragraphs` with your own text:

```python
my_text = [
    "Your first paragraph here...",
    "Your second paragraph here...",
    "And so on...",
]

results = extract_concepts_and_arguments(my_text, api_key)
```

## What Gets Extracted

### 1. Concept Mentions
Technical terms, key ideas, and important concepts:

```json
{
  "surface_form": "commodity",
  "sentence_index": 0,
  "is_technical_term": true,
  "normalized_form": null,
  "confidence": 0.9
}
```

### 2. Atomic Claims (Arguments)
Individual assertions, theses, and propositions:

```json
{
  "claim_text_canonical": "A commodity satisfies human wants",
  "claim_type": "thesis",
  "polarity": "assert",
  "modality": "is",
  "evidence_sentence_indices": [0, 1],
  "about_terms": ["commodity", "human wants"],
  "confidence": 0.85
}
```

## Prompt Structure

The prompts follow this pattern (from `nlp_pipeline/stage_a/prompts.py`):

```
Task: [What to extract]
Rules:
- CONTEXT is read-only (for understanding, not extraction)
- sentence_index refers to TARGET sentences only
- [Specific extraction rules...]
Return ONLY a JSON object of the form:
{schema example}

CONTEXT:
[Previous sentences for context]

TARGET:
[Sentences to extract from]
```

## Understanding the Output

### Claim Types
- **definition**: Defines a term or concept
- **thesis**: Main argument or position
- **empirical**: Observation or fact about the world
- **normative**: Value judgment or prescription
- **methodological**: About how to approach analysis
- **objection**: Counter-argument
- **reply**: Response to objection

### Polarity
- **assert**: Affirming the claim
- **deny**: Negating the claim
- **conditional**: If-then or hypothetical

### Modality
Indicates the mode of the claim:
- **is**: Actual state
- **can/could**: Possibility
- **must**: Necessity
- **should/ought**: Obligation
- **appears_as**: Phenomenal appearance
- **becomes**: Dialectical transformation
- **in_essence_is**: Essential nature

## Cost Estimation

Using Claude 3.5 Sonnet (as of 2025):
- Input: $3.00 per million tokens
- Output: $15.00 per million tokens

Typical extraction costs:
- ~1000 words of text: ~$0.02-0.05
- ~10,000 words (short book chapter): ~$0.20-0.50
- ~100,000 words (full book): ~$2-5

## Customization

### Change the Extraction Schema

Edit the prompt to extract different fields:

```python
def my_custom_prompt(*, context: list[str], target: list[str]) -> str:
    return (
        "Task: Extract [your custom extraction task].\n"
        "Return ONLY a JSON object:\n"
        '{"results":[{"field1": "...", "field2": 123}]}\n\n'
        f"CONTEXT:\n{_render_sentences(context)}\n\n"
        f"TARGET:\n{_render_sentences(target)}\n"
    )
```

### Use Different Models

```python
# Faster/cheaper: Claude 3 Haiku
response = client.messages.create(
    model="claude-3-haiku-20240307",
    max_tokens=2000,
    messages=[{"role": "user", "content": prompt}]
)

# More capable: Claude 3 Opus
response = client.messages.create(
    model="claude-3-opus-20240229",
    max_tokens=4000,
    messages=[{"role": "user", "content": prompt}]
)
```

### Add Context Window

The example uses the last 2 sentences from the previous paragraph as context:

```python
# Larger context window
context = prev_sentences[-5:]  # Last 5 sentences

# No context
context = []

# Custom context
context = ["Background info...", "More context..."]
```

## Integration with Grundrisse Pipeline

To integrate extracted data into the Grundrisse database:

```python
from grundrisse_core.db.models import ConceptMention, Claim
from grundrisse_core.db.session import SessionLocal

with SessionLocal() as session:
    # Save concept mention
    mention = ConceptMention(
        span_id=sentence_span_id,  # Get from your SentenceSpan
        surface_form="commodity",
        is_technical=True,
        confidence=0.9,
    )
    session.add(mention)

    # Save claim
    claim = Claim(
        claim_text="A commodity satisfies human wants",
        claim_type=ClaimType.thesis,
        polarity=Polarity.assert,
        confidence=0.85,
    )
    session.add(claim)

    session.commit()
```

See `nlp_pipeline/stage_a/run.py::_call_a1()` and `_call_a3()` for full integration examples.
