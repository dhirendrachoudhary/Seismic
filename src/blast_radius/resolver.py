"""Resolve changed line ranges to FunctionNode objects via SQLite graph lookup."""

from typing import Optional

from src.blast_radius.git_diff import ChangedRange
from src.blast_radius.graph import CodeGraph
from src.blast_radius.parser.python import FunctionNode


class FunctionResolver:
    """Resolve changed lines to changed functions via CodeGraph."""

    FUZZY_SEARCH_RADIUS = 3  # Search ±3 lines if exact match fails

    def __init__(self, graph: CodeGraph):
        """
        Initialize resolver with a CodeGraph instance.

        Args:
            graph: CodeGraph instance (must have indexed database)
        """
        self.graph = graph

    def resolve_to_functions(
        self, changed_ranges: list[ChangedRange]
    ) -> list[FunctionNode]:
        """
        Resolve changed lines to functions.

        For each changed line, queries graph.find_by_line() to find the
        containing function. Deduplicates by uid and returns sorted list.

        Algorithm:
        1. For each ChangedRange (file with changed lines)
        2.   For each line number in lines
        3.     Try exact match: graph.find_by_line(file_path, line)
        4.     If found: add to set (deduplicate by uid)
        5.     If not found: try fuzzy search ±3 lines
        6. Return deduplicated list sorted by uid

        Args:
            changed_ranges: List of ChangedRange objects from GitDiffParser

        Returns:
            List of FunctionNode objects for changed functions (ground zero)
        """
        if not changed_ranges:
            return []

        changed_functions: dict[str, FunctionNode] = {}

        for changed_range in changed_ranges:
            for line_num in changed_range.lines:
                # Try exact match first
                fn = self.graph.find_by_line(changed_range.file_path, line_num)

                if fn:
                    # Store by uid to deduplicate
                    changed_functions[fn.uid] = fn
                else:
                    # Try fuzzy match if exact match fails
                    fn = self._fuzzy_match(changed_range.file_path, line_num)
                    if fn:
                        changed_functions[fn.uid] = fn

        # Return deduplicated list sorted by uid
        return sorted(changed_functions.values(), key=lambda fn: fn.uid)

    def _fuzzy_match(self, file_path: str, line: int) -> Optional[FunctionNode]:
        """
        Fallback: search ±3 lines if exact match fails.

        This typically indicates the index may be out of date (source code
        changed but index wasn't rebuilt). Logs a warning to alert the user.

        Args:
            file_path: Path to the changed file
            line: Line number that didn't match exactly

        Returns:
            FunctionNode if found in fuzzy search, None otherwise
        """
        for delta in range(1, self.FUZZY_SEARCH_RADIUS + 1):
            # Try line - delta
            fn = self.graph.find_by_line(file_path, line - delta)
            if fn:
                print(
                    f"⚠️  Fuzzy match: line {line} → {fn.name}@{fn.file_path}:{fn.line_start} "
                    f"(±{delta}). Index may be stale; re-run 'blast-radius index' if needed."
                )
                return fn

            # Try line + delta
            fn = self.graph.find_by_line(file_path, line + delta)
            if fn:
                print(
                    f"⚠️  Fuzzy match: line {line} → {fn.name}@{fn.file_path}:{fn.line_start} "
                    f"(±{delta}). Index may be stale; re-run 'blast-radius index' if needed."
                )
                return fn

        return None
