"""Generic runtime integrity primitives: cycle detection, duplicate-link protection, and inheritance-chain well-formedness (C-031). Callers supply their own concrete edges, links, and orders; no downstream vocabulary is imported here."""

from plan_manager.domain.runtime_validation import RuntimeValidationError


class DuplicateLinkError(RuntimeValidationError):
    """Raised when a candidate link is already registered (C-031's generic duplicate-link
    guard); maps to DUPLICATE_LINK at the command boundary."""


class LinkCycleError(RuntimeValidationError):
    """Raised when a directed graph of edges contains a cycle (C-031's generic cycle-detection
    guard); maps to LINK_CYCLE at the command boundary."""


def detect_cycle(edges: list[tuple[str, str]]) -> None:
    """Detect cycles in a directed graph via depth-first search.

    Treats edges as a directed graph of (from, to) pairs and raises
    RuntimeValidationError if the graph contains a cycle. This function is used
    by callers for BOTH blocking-link cycles AND project-dependency cycles, and
    imports no downstream vocabulary — the caller supplies the concrete edge list.

    Parameters:
        edges: A list of directed (from_node, to_node) string-identifier pairs.

    Raises:
        RuntimeValidationError: When a cycle is found, with the cycle's node
            sequence in the message.
    """
    graph: dict[str, list[str]] = {}
    for src, dst in edges:
        graph.setdefault(src, []).append(dst)
        graph.setdefault(dst, [])

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in graph}

    def visit(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in graph.get(node, []):
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                raise LinkCycleError(f"cycle detected: {' -> '.join(cycle)}")
            if color[neighbor] == WHITE:
                visit(neighbor, path)
        path.pop()
        color[node] = BLACK

    for node in list(graph):
        if color[node] == WHITE:
            visit(node, [])


def ensure_no_duplicate(existing: set[tuple], candidate: tuple) -> None:
    """Ensure a candidate link is not already registered.

    Raises RuntimeValidationError if candidate is already present in existing,
    realizing C-031's duplicate-link-protection guarantee generically for any
    tuple-shaped link representation supplied by the caller.

    Parameters:
        existing: The set of already-registered link tuples.
        candidate: The candidate link tuple to check for duplication.

    Raises:
        RuntimeValidationError: When candidate is already in existing.
    """
    if candidate in existing:
        raise DuplicateLinkError(f"duplicate link: {candidate!r}")


def verify_inheritance_chain(levels: list[str], allowed_order: list[str]) -> None:
    """Verify that a level chain is a valid subsequence of an allowed order.

    Raises RuntimeValidationError unless levels is a subsequence of allowed_order
    (relative order preserved, no element repeated), realizing C-031's
    model-binding-inheritance-verification guarantee generically — the concrete
    order is always supplied by the caller (a downstream branch); this function
    references no fixed downstream ordering itself.

    Parameters:
        levels: The candidate ordered list of levels to verify.
        allowed_order: The caller-supplied total order that levels must be
            consistent with.

    Raises:
        RuntimeValidationError: When an element of levels repeats, when an
            element of levels is not present in allowed_order, or when the
            relative order of levels is inconsistent with allowed_order.
    """
    seen: set[str] = set()
    last_index = -1
    for level in levels:
        if level in seen:
            raise RuntimeValidationError(f"level repeated in chain: {level!r}")
        seen.add(level)
        if level not in allowed_order:
            raise RuntimeValidationError(f"level not in allowed_order: {level!r}")
        index = allowed_order.index(level)
        if index <= last_index:
            raise RuntimeValidationError(
                f"level {level!r} out of order relative to allowed_order {allowed_order!r}"
            )
        last_index = index
