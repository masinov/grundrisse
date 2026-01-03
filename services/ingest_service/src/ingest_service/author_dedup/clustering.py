"""Cluster similar author names for deduplication."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def normalize_for_matching(name: str) -> str:
    """
    Normalize name for fuzzy matching.

    - Lowercase
    - Remove periods and extra spaces
    - Remove common suffixes (Jr., Sr., etc.)
    """
    name = name.lower()
    name = name.replace(".", "")
    name = re.sub(r"\s+", " ", name).strip()

    # Remove common suffixes
    suffixes = [" jr", " sr", " iii", " ii", " iv"]
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()

    return name


def similarity_score(name1: str, name2: str) -> float:
    """
    Calculate similarity score between two names (0.0 to 1.0).

    Uses SequenceMatcher for fuzzy string matching.
    """
    norm1 = normalize_for_matching(name1)
    norm2 = normalize_for_matching(name2)

    return SequenceMatcher(None, norm1, norm2).ratio()


def is_likely_same_author(name1: str, name2: str, threshold: float = 0.85) -> bool:
    """
    Check if two names likely refer to the same author.

    Args:
        name1: First name
        name2: Second name
        threshold: Similarity threshold (0.0-1.0)

    Returns:
        True if names are likely the same author
    """
    # Exact match after normalization
    if normalize_for_matching(name1) == normalize_for_matching(name2):
        return True

    # High similarity score
    if similarity_score(name1, name2) >= threshold:
        return True

    # Check for initial variations (e.g., "V. I. Lenin" vs "Vladimir Lenin")
    norm1 = normalize_for_matching(name1)
    norm2 = normalize_for_matching(name2)

    # Split into tokens
    tokens1 = norm1.split()
    tokens2 = norm2.split()

    # Check if one is a subset of the other (e.g., "Lenin" in "Vladimir Lenin")
    if len(tokens1) == 1 and tokens1[0] in tokens2:
        return True
    if len(tokens2) == 1 and tokens2[0] in tokens1:
        return True

    # Check for initial matching (e.g., "v i lenin" vs "vladimir lenin")
    # If all initials of one match the start of words in the other
    if len(tokens1) <= len(tokens2):
        if all(
            t1[0] == t2[0] for t1, t2 in zip(tokens1, tokens2) if len(t1) == 1 or len(t2) == 1
        ):
            # Also check that last names match
            if tokens1[-1] == tokens2[-1] or similarity_score(tokens1[-1], tokens2[-1]) > 0.85:
                return True

    return False


def cluster_similar_names(
    names: list[str],
    *,
    threshold: float = 0.85,
) -> list[list[str]]:
    """
    Cluster similar author names together.

    Args:
        names: List of author names
        threshold: Similarity threshold

    Returns:
        List of clusters, each cluster is a list of similar names
    """
    # Union-find data structure
    parent = {name: name for name in names}

    def find(name: str) -> str:
        if parent[name] != name:
            parent[name] = find(parent[name])
        return parent[name]

    def union(name1: str, name2: str) -> None:
        root1 = find(name1)
        root2 = find(name2)
        if root1 != root2:
            parent[root2] = root1

    # Compare all pairs
    for i, name1 in enumerate(names):
        for name2 in names[i + 1 :]:
            if is_likely_same_author(name1, name2, threshold=threshold):
                union(name1, name2)

    # Group by root
    clusters_dict: dict[str, list[str]] = {}
    for name in names:
        root = find(name)
        if root not in clusters_dict:
            clusters_dict[root] = []
        clusters_dict[root].append(name)

    # Return clusters with 2+ members (singletons don't need deduplication)
    clusters = [cluster for cluster in clusters_dict.values() if len(cluster) > 1]

    # Sort by size (largest first)
    clusters.sort(key=len, reverse=True)

    return clusters
