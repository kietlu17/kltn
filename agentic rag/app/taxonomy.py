from __future__ import annotations

import hashlib
import re
import unicodedata


_PATH_SEPARATOR = re.compile(r"\s*(?:›|>|»|→)\s*")
_SOURCE_PREFIX = re.compile(r"^.{1,48}?\s*[·•]\s*")


def _clean_segment(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" /-")


def _path_key(parts: list[str]) -> str:
    normalized = "/".join(
        "".join(
            char
            for char in unicodedata.normalize("NFD", part.casefold())
            if not unicodedata.combining(char)
        )
        for part in parts
    )
    return "taxonomy:" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _encoded_path(name: str) -> list[str]:
    # Merchant prefixes such as "MUJI ·" describe the source, not a browse node.
    browse_name = _SOURCE_PREFIX.sub("", _clean_segment(name), count=1)
    return [
        segment
        for raw in _PATH_SEPARATOR.split(browse_name)
        if (segment := _clean_segment(raw))
    ]


def _category_path(category: dict, by_id: dict[str, dict]) -> list[str]:
    path: list[str] = []
    current = category
    visited: set[str] = set()
    while current:
        current_id = str(current.get("id") or current.get("_id") or "")
        if current_id and current_id in visited:
            break
        if current_id:
            visited.add(current_id)
        name = _clean_segment(current.get("name"))
        if name:
            path.append(name)
        parent_id = str(current.get("parentId") or "")
        current = by_id.get(parent_id) if parent_id else None
    if len(path) > 1:
        return list(reversed(path))
    return _encoded_path(category.get("name", ""))


def build_catalog_tree(categories: list[dict]) -> list[dict]:
    """Build a deterministic browse tree without inventing catalog semantics.

    Explicit parent relationships win. Legacy flattened categories may encode a
    path in their name (for example ``Fashion › Men › T-shirts``); those paths
    are expanded into virtual nodes. Unstructured names remain root nodes.
    """
    by_id = {
        str(item.get("id") or item.get("_id")): item
        for item in categories
        if isinstance(item, dict) and (item.get("id") or item.get("_id"))
    }
    roots: dict[str, dict] = {}
    for category in categories:
        if not isinstance(category, dict):
            continue
        category_id = str(category.get("id") or category.get("_id") or "")
        path = _category_path(category, by_id)
        if not category_id or not path:
            continue
        siblings = roots
        prefix: list[str] = []
        for index, segment in enumerate(path):
            prefix.append(segment)
            key = _path_key(prefix)
            node = siblings.setdefault(
                key,
                {
                    "id": key,
                    "name": segment,
                    "path": list(prefix),
                    "categoryIds": set(),
                    "leafCategoryIds": set(),
                    "_children": {},
                },
            )
            node["categoryIds"].add(category_id)
            if index == len(path) - 1:
                node["leafCategoryIds"].add(category_id)
            siblings = node["_children"]

    def serialize(node: dict) -> dict:
        children = sorted(
            (serialize(child) for child in node["_children"].values()),
            key=lambda child: (child["name"].casefold(), child["id"]),
        )
        return {
            "id": node["id"],
            "name": node["name"],
            "path": node["path"],
            "categoryIds": sorted(node["categoryIds"]),
            "leafCategoryIds": sorted(node["leafCategoryIds"]),
            "childCount": len(children),
            "children": children,
        }

    return sorted(
        (serialize(node) for node in roots.values()),
        key=lambda node: (node["name"].casefold(), node["id"]),
    )


def compact_catalog_tree(
    nodes: list[dict], *, max_depth: int = 3, max_children: int = 16
) -> list[dict]:
    """Bound the tree passed to the LLM while retaining traversal metadata."""

    def compact(node: dict, depth: int) -> dict:
        children = node.get("children", [])
        visible = children[:max_children] if depth < max_depth else []
        return {
            "id": node["id"],
            "name": node["name"],
            "path": node["path"],
            "categoryIds": node["categoryIds"],
            "childCount": len(children),
            "hiddenChildCount": max(0, len(children) - len(visible)),
            "children": [compact(child, depth + 1) for child in visible],
        }

    return [compact(node, 1) for node in nodes[:max_children]]


def resolve_category_ids(nodes: list[dict], value: str) -> list[str]:
    """Resolve a natural category path to descendant source category IDs.

    Resolution is deliberately conservative: a node name must be fully present
    in the requested phrase. Ancestor matches only rank otherwise valid nodes,
    so a generic token cannot silently force an unrelated catalog branch.
    """

    def terms(text: object) -> set[str]:
        normalized = unicodedata.normalize("NFD", str(text or "").casefold())
        normalized = normalized.replace("đ", "d")
        normalized = "".join(
            char for char in normalized if not unicodedata.combining(char)
        )
        return set(re.findall(r"[a-z0-9]+", normalized))

    requested = terms(value)
    if not requested:
        return []
    order = re.findall(
        r"[a-z0-9]+",
        "".join(
            char
            for char in unicodedata.normalize("NFD", str(value).casefold()).replace("đ", "d")
            if not unicodedata.combining(char)
        ),
    )
    first_position = {term: order.index(term) for term in requested}
    ranked: list[tuple[int, dict]] = []

    def visit(node: dict) -> None:
        name_terms = terms(node.get("name"))
        if name_terms and name_terms <= requested:
            path_terms = set().union(*(terms(part) for part in node.get("path", [])))
            score = 4 * len(name_terms) + len(path_terms & requested)
            if name_terms == requested:
                score += 20
            score += len(node.get("path", []))
            ranked.append((score, node))
        for child in node.get("children", []):
            visit(child)

    for root in nodes:
        visit(root)
    if not ranked:
        return []
    best = max(score for score, _node in ranked)
    tied = [node for score, node in ranked if score == best]
    # Vietnamese puts the head noun first: in "balo laptop" the branch named
    # earliest in the phrase wins a tie.
    position = {
        id(node): min(first_position[term] for term in terms(node.get("name")))
        for node in tied
    }
    earliest = min(position.values())
    return sorted(
        {
            category_id
            for node in tied
            if position[id(node)] == earliest
            for category_id in node.get("categoryIds", [])
            if re.fullmatch(r"[a-fA-F0-9]{24}", str(category_id))
        }
    )
