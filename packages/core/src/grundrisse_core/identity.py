from __future__ import annotations

import uuid

NAMESPACE_AUTHOR = uuid.UUID("f8e4a56a-5f5f-4c4e-8f2e-6d91ce1fb33e")
NAMESPACE_WORK = uuid.UUID("09f2c7d1-4a2a-4f48-b0fd-7d3719f93a0c")
NAMESPACE_EDITION = uuid.UUID("1a7c3a40-6b3b-4bdb-a0b2-c2a15c66411a")


def stable_uuid(namespace: uuid.UUID, name: str) -> uuid.UUID:
    return uuid.uuid5(namespace, name.strip())


def author_id_for(name_canonical: str) -> uuid.UUID:
    return stable_uuid(NAMESPACE_AUTHOR, name_canonical)


def work_id_for(*, author_id: uuid.UUID, title: str) -> uuid.UUID:
    return stable_uuid(NAMESPACE_WORK, f"{author_id}:{title.strip()}")


def edition_id_for(*, work_id: uuid.UUID, language: str, source_url: str) -> uuid.UUID:
    return stable_uuid(NAMESPACE_EDITION, f"{work_id}:{language.strip()}:{source_url.strip()}")

