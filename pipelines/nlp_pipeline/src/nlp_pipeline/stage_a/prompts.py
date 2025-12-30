from __future__ import annotations

def render_a1_prompt(*, context_only: list[str], target: list[str]) -> str:
    return (
        "Task: Extract concept mentions from TARGET only.\n"
        "Rules:\n"
        "- CONTEXT_ONLY is read-only and must not be referenced in outputs.\n"
        "- sentence_index must refer to TARGET sentence indices (0..len(TARGET)-1).\n"
        "- Prefer fewer, higher-confidence mentions.\n"
        "Return ONLY a JSON object of the form:\n"
        '{"mentions":[{"surface_form": "...", "sentence_index": 0, "is_technical_term": true, '
        '"start_char_in_sentence": 0, "end_char_in_sentence": 10, "normalized_form": null, '
        '"candidate_gloss": null, "confidence": 0.8}]}\n\n'
        f"CONTEXT_ONLY:\n{_render_sentences(context_only)}\n\n"
        f"TARGET:\n{_render_sentences(target)}\n"
    )


def render_a3_prompt(*, context_only: list[str], target: list[str]) -> str:
    return (
        "Task: Extract atomic claims asserted in TARGET.\n"
        "Rules:\n"
        "- CONTEXT_ONLY is read-only and must not be referenced in evidence_sentence_indices.\n"
        "- evidence_sentence_indices must be non-empty and refer only to TARGET indices.\n"
        "- Include dialectical_status and modality when present (appearance/essence matters).\n"
        "- For modality, use one of: is, will, would, can, could, cannot, must, should, ought, may, appears_as, becomes, in_essence_is; otherwise null.\n"
        "- For dialectical_status, use one of: none, tension_pair, appearance_essence, developmental.\n"
        "- Set attribution=self unless the author is explicitly citing/interlocuting.\n"
        "- Prefer fewer, higher-confidence claims; never invent evidence.\n"
        "Return ONLY a JSON object of the form:\n"
        '{"claims":[{"claim_text_canonical":"...", "claim_type":"thesis", "polarity":"assert", '
        '"modality":"is", "dialectical_status":"none", "scope": null, "attribution":"self", '
        '"evidence_sentence_indices":[0], "about_terms":[], "confidence":0.7}]}\n\n'
        f"CONTEXT_ONLY:\n{_render_sentences(context_only)}\n\n"
        f"TARGET:\n{_render_sentences(target)}\n"
    )


def render_a13_prompt(*, context_only: list[str], target: list[str]) -> str:
    return (
        "Task: From TARGET only, extract (A1) concept mentions and (A3) atomic claims.\n"
        "Rules:\n"
        "- CONTEXT_ONLY is read-only and must not be referenced in sentence indices.\n"
        "- sentence_index and evidence_sentence_indices refer ONLY to TARGET indices.\n"
        "- Every claim must cite non-empty evidence_sentence_indices.\n"
        "- claim_type must be one of: definition, thesis, empirical, normative, methodological, objection, reply.\n"
        "- polarity must be one of: assert, deny, conditional.\n"
        "- dialectical_status must be one of: none, tension_pair, appearance_essence, developmental.\n"
        "- attribution must be one of: self, citation, interlocutor.\n"
        "- modality must be one of: is, will, would, can, could, cannot, must, should, ought, may, appears_as, becomes, in_essence_is; otherwise null.\n"
        "Return ONLY a JSON object of the form:\n"
        '{"mentions":[{"surface_form":"...","sentence_index":0,"is_technical_term":true}],'
        '"claims":[{"claim_text_canonical":"...","claim_type":"thesis","polarity":"assert","modality":null,'
        '"dialectical_status":"none","scope":null,"attribution":"self","evidence_sentence_indices":[0],'
        '"about_terms":[]}]}'
        "\n\n"
        f"CONTEXT_ONLY:\n{_render_sentences(context_only)}\n\n"
        f"TARGET:\n{_render_sentences(target)}\n"
    )


def _render_sentences(sentences: list[str]) -> str:
    if not sentences:
        return "(none)"
    lines = []
    for idx, text in enumerate(sentences):
        lines.append(f"[{idx}] {text}")
    return "\n".join(lines)
