from __future__ import annotations

import enum


class WorkType(str, enum.Enum):
    book = "book"
    article = "article"
    letter = "letter"
    speech = "speech"
    other = "other"


class TextBlockType(str, enum.Enum):
    chapter = "chapter"
    section = "section"
    subsection = "subsection"
    other = "other"


class AuthorRole(str, enum.Enum):
    author = "author"
    editor = "editor"
    translator = "translator"
    prefacer = "prefacer"
    commentator = "commentator"


class BlockSubtype(str, enum.Enum):
    preface = "preface"
    afterword = "afterword"
    footnote = "footnote"
    editor_note = "editor_note"
    letter = "letter"
    appendix = "appendix"
    toc = "toc"
    navigation = "navigation"
    license = "license"
    metadata = "metadata"
    study_guide = "study_guide"
    other = "other"


class DialecticalStatus(str, enum.Enum):
    none = "none"
    tension_pair = "tension_pair"
    appearance_essence = "appearance_essence"
    developmental = "developmental"


class ClaimType(str, enum.Enum):
    definition = "definition"
    thesis = "thesis"
    empirical = "empirical"
    normative = "normative"
    methodological = "methodological"
    objection = "objection"
    reply = "reply"


class Polarity(str, enum.Enum):
    assert_ = "assert"
    deny = "deny"
    conditional = "conditional"


class Modality(str, enum.Enum):
    is_ = "is"
    will = "will"
    would = "would"
    can = "can"
    could = "could"
    cannot = "cannot"
    must = "must"
    should = "should"
    ought = "ought"
    may = "may"
    appears_as = "appears_as"
    becomes = "becomes"
    in_essence_is = "in_essence_is"


class ClaimAttribution(str, enum.Enum):
    self_ = "self"
    citation = "citation"
    interlocutor = "interlocutor"


class ClaimLinkType(str, enum.Enum):
    equivalent = "equivalent"
    refines = "refines"
    applies = "applies"
    criticizes = "criticizes"
    logical_contradiction = "logical_contradiction"
    apparent_contradiction = "apparent_contradiction"
    dialectical_sublation = "dialectical_sublation"


class AlignmentType(str, enum.Enum):
    translation_of = "translation_of"
    parallel = "parallel"
    loose_parallel = "loose_parallel"
