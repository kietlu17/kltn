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


def _terms(text: object) -> set[str]:
    normalized = unicodedata.normalize("NFD", str(text or "").casefold())
    normalized = normalized.replace("đ", "d")
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return set(re.findall(r"[a-z0-9]+", normalized))


# Everyday names of a whole branch ("quần áo nữ" is women's fashion, not
# women's trousers), on accent-free text.
_BRANCH_ALIASES = (
    ("quan ao", "thoi trang"),
    ("do mac", "thoi trang"),
    ("thiet bi dien tu", "dien tu"),
    ("do dien tu", "dien tu"),
    ("do cong nghe", "dien tu"),
    ("cong nghe", "dien tu"),
    ("my pham", "lam dep"),
    ("do an", "thuc pham"),
    ("do gia dung", "nha cua"),
)


def _folded_words(value: object) -> str:
    normalized = unicodedata.normalize("NFD", str(value or "").casefold()).replace("đ", "d")
    return " ".join(re.findall(
        r"[a-z0-9]+", "".join(char for char in normalized if not unicodedata.combining(char))
    ))


def _path_text(parts: list[str]) -> str:
    return " › ".join(parts)


def category_paths(categories: list[dict]) -> dict[str, str]:
    """Full display path of every category id ("Thời trang › Nữ › Áo thun nữ")."""
    by_id = {
        str(item.get("id") or item.get("_id")): item
        for item in categories
        if isinstance(item, dict) and (item.get("id") or item.get("_id"))
    }
    return {
        category_id: _path_text(_category_path(category, by_id))
        for category_id, category in by_id.items()
    }


def category_path_list(nodes: list[dict], *, max_depth: int = 3, limit: int = 300) -> list[str]:
    """Browse paths the semantic model may pick from, shallow ones first."""
    paths: list[str] = []
    level = list(nodes)
    for _depth in range(max_depth):
        next_level = []
        for node in level:
            paths.append(_path_text(node.get("path") or [node.get("name", "")]))
            next_level.extend(node.get("children", []))
        level = next_level
    return paths[:limit]


def resolve_category_path(nodes: list[dict], value: str) -> list[str]:
    """Category ids of the node whose path is exactly ``value``, as the
    semantic model copied it from category_path_list (accents and separators
    may differ). [] when no node has that path."""
    wanted = [
        " ".join(sorted(_terms(part)))
        for part in _PATH_SEPARATOR.split(str(value or ""))
        if _terms(part)
    ]
    if not wanted:
        return []

    def visit(node: dict) -> list[str] | None:
        path = [" ".join(sorted(_terms(part))) for part in node.get("path", [])]
        if path == wanted:
            return [
                str(category_id) for category_id in node.get("categoryIds", [])
                if re.fullmatch(r"[a-fA-F0-9]{24}", str(category_id))
            ]
        if path == wanted[: len(path)]:
            for child in node.get("children", []):
                found = visit(child)
                if found is not None:
                    return found
        return None

    for root in nodes:
        found = visit(root)
        if found is not None:
            return sorted(found)
    return []


def _valid_ids(found: list[dict]) -> list[str]:
    return sorted({
        str(category_id)
        for node in found
        for category_id in node.get("categoryIds", [])
        if re.fullmatch(r"[a-fA-F0-9]{24}", str(category_id))
    })


def _covering(nodes: list[dict], requested: set[str]) -> list[str]:
    """Nodes whose path holds every requested word and whose own name holds
    at least one; a match stops the descent (its ids include descendants)."""
    found: list[dict] = []

    def visit(node: dict) -> None:
        path_terms = set().union(*(_terms(part) for part in node.get("path", [])))
        if requested <= path_terms and _terms(node.get("name")) & requested:
            found.append(node)
            return
        for child in node.get("children", []):
            visit(child)

    for root in nodes:
        visit(root)
    return _valid_ids(found)


def _best_named(nodes: list[dict], phrase: str) -> list[str]:
    """The most specific nodes whose whole name appears in the phrase; ties
    go to the branch named first (Vietnamese puts the head noun first)."""
    requested = _terms(phrase)
    order = phrase.split()
    first_position = {term: order.index(term) for term in requested}
    ranked: list[tuple[int, dict]] = []

    def visit(node: dict) -> None:
        name_terms = _terms(node.get("name"))
        if name_terms and name_terms <= requested:
            path_terms = set().union(*(_terms(part) for part in node.get("path", [])))
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
    position = {
        id(node): min(first_position[term] for term in _terms(node.get("name")))
        for node in tied
    }
    earliest = min(position.values())
    return _valid_ids([node for node in tied if position[id(node)] == earliest])


def resolve_category_ids(nodes: list[dict], value: str) -> list[str]:
    """Resolve a natural category phrase to descendant source category IDs.

    1. Covering nodes: every requested word appears on the node's path and
       the node itself names part of it. "áo thun" covers Nam › Áo Thun,
       Nữ › Áo Thun and every "Áo thun nam/nữ/trẻ em" leaf, so no shop's
       branch is lost; "áo thun nữ" covers only women's T-shirts.
    2. Otherwise the most specific node whose whole name appears in the
       phrase ("tai nghe bluetooth chống ồn" -> Tai nghe). Ancestor matches
       only rank otherwise valid nodes, so a generic token cannot silently
       force an unrelated catalog branch.
    Branch aliases ("quần áo nữ" -> "thời trang nữ") are tried before the
    literal phrase at each step, so a catalog whose root is literally named
    "Quần áo" still matches.
    """
    original = _folded_words(value)
    if not original:
        return []
    aliased = original
    for phrase, root in _BRANCH_ALIASES:
        aliased = re.sub(rf"(?<!\w){phrase}(?!\w)", root, aliased)
    phrases = list(dict.fromkeys([aliased, original]))
    for phrase in phrases:
        if found := _covering(nodes, _terms(phrase)):
            return found
    for phrase in phrases:
        if found := _best_named(nodes, phrase):
            return found
    return []
