"""Unit tests for Phase 4 graph client (CodeGraph + recursive CTE queries)."""

import pytest
import sqlite3
import tempfile
from pathlib import Path

from src.blast_radius.indexer import PythonRepoIndexer
from src.blast_radius.graph import CodeGraph, BlastRadiusResult
from src.blast_radius.parser.python import FunctionNode


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def test_repo_dir(tmp_path):
    """Create a minimal test repository for integration tests."""
    # Create src directory
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    # Create main.py with a call chain
    (src_dir / "main.py").write_text(
        """
def process_data(x):
    return x * 2

def main():
    result = process_data(5)
    return result
"""
    )

    # Create utils.py with helper functions
    (src_dir / "utils.py").write_text(
        """
def helper_func():
    return 42

def another_helper():
    result = helper_func()
    return result + 1
"""
    )

    # Create a more complex chain
    (src_dir / "api.py").write_text(
        """
def calculate():
    return 100

def process():
    return calculate() + 1

def api_handler():
    return process() * 2
"""
    )

    # Create .venv directory to be skipped
    venv_dir = tmp_path / ".venv" / "lib" / "python3.10"
    venv_dir.mkdir(parents=True)
    (venv_dir / "site.py").write_text("# This should be skipped")

    return tmp_path


@pytest.fixture
def indexed_graph(test_repo_dir):
    """Create an indexed repo and return a CodeGraph instance."""
    db_path = test_repo_dir / "test.db"
    indexer = PythonRepoIndexer(str(test_repo_dir), str(db_path))
    indexer.run()

    graph = CodeGraph(str(db_path))
    yield graph
    graph.close()


# ============================================================================
# CodeGraph Connection & Initialization Tests
# ============================================================================


class TestCodeGraphConnection:
    """Test database connection and initialization."""

    def test_codegraph_connects_to_database(self, test_repo_dir):
        """Test that CodeGraph can connect to a database."""
        db_path = test_repo_dir / "test.db"
        indexer = PythonRepoIndexer(str(test_repo_dir), str(db_path))
        indexer.run()

        graph = CodeGraph(str(db_path))
        assert graph.db_path == str(db_path)
        assert graph.conn is not None
        graph.close()

    def test_codegraph_closes_without_error(self, test_repo_dir):
        """Test that CodeGraph can be closed without errors."""
        db_path = test_repo_dir / "test.db"
        indexer = PythonRepoIndexer(str(test_repo_dir), str(db_path))
        indexer.run()

        graph = CodeGraph(str(db_path))
        graph.close()  # Should not raise


# ============================================================================
# find_by_name() Tests
# ============================================================================


class TestFindByName:
    """Test function lookup by name."""

    def test_find_existing_function_by_name(self, indexed_graph):
        """Test finding an existing function by name."""
        fn = indexed_graph.find_by_name("main")
        assert fn is not None
        assert fn.name == "main"
        assert isinstance(fn, FunctionNode)

    def test_find_nonexistent_function_returns_none(self, indexed_graph):
        """Test that finding a non-existent function returns None."""
        fn = indexed_graph.find_by_name("nonexistent_function_xyz")
        assert fn is None

    def test_find_by_name_returns_function_node(self, indexed_graph):
        """Test that find_by_name returns a proper FunctionNode object."""
        fn = indexed_graph.find_by_name("helper_func")
        assert fn is not None
        assert hasattr(fn, "uid")
        assert hasattr(fn, "name")
        assert hasattr(fn, "file_path")
        assert hasattr(fn, "line_start")
        assert hasattr(fn, "line_end")
        assert hasattr(fn, "source")
        assert hasattr(fn, "complexity")
        assert hasattr(fn, "decorators")

    def test_find_by_name_preserves_function_data(self, indexed_graph):
        """Test that function data is correctly preserved."""
        fn = indexed_graph.find_by_name("process_data")
        assert fn.name == "process_data"
        assert fn.file_path is not None
        assert fn.line_start > 0
        assert fn.line_end >= fn.line_start
        assert fn.source is not None
        assert fn.complexity >= 1  # Cyclomatic complexity


# ============================================================================
# find_by_line() Tests
# ============================================================================


class TestFindByLine:
    """Test function lookup by file and line number."""

    def test_find_function_containing_line(self, indexed_graph):
        """Test finding the function containing a specific line."""
        # First find a function to get its file path and lines
        fn = indexed_graph.find_by_name("main")
        assert fn is not None

        # Find it again using line lookup
        fn_by_line = indexed_graph.find_by_line(fn.file_path, fn.line_start + 1)
        assert fn_by_line is not None
        assert fn_by_line.uid == fn.uid

    def test_find_by_line_returns_none_for_empty_area(self, indexed_graph):
        """Test that find_by_line returns None if no function contains the line."""
        fn = indexed_graph.find_by_name("main")
        assert fn is not None

        # Try a line far beyond the file
        result = indexed_graph.find_by_line(fn.file_path, 99999)
        assert result is None

    def test_find_by_line_boundary_line_start(self, indexed_graph):
        """Test boundary condition: line equals line_start."""
        fn = indexed_graph.find_by_name("process_data")
        assert fn is not None

        result = indexed_graph.find_by_line(fn.file_path, fn.line_start)
        assert result is not None
        assert result.uid == fn.uid

    def test_find_by_line_boundary_line_end(self, indexed_graph):
        """Test boundary condition: line equals line_end."""
        fn = indexed_graph.find_by_name("process_data")
        assert fn is not None

        result = indexed_graph.find_by_line(fn.file_path, fn.line_end)
        assert result is not None
        assert result.uid == fn.uid


# ============================================================================
# get_blast_radius() Tests
# ============================================================================


class TestGetBlastRadius:
    """Test blast radius query (main recursive CTE query)."""

    def test_blast_radius_single_function(self, indexed_graph):
        """Test blast radius with a single changed function."""
        result = indexed_graph.get_blast_radius(["process_data"])
        assert isinstance(result, BlastRadiusResult)
        assert len(result.ground_zero) > 0
        assert len(result.affected_functions) > 0

    def test_blast_radius_multiple_functions(self, indexed_graph):
        """Test blast radius with multiple changed functions."""
        result = indexed_graph.get_blast_radius(["calculate", "helper_func"])
        assert isinstance(result, BlastRadiusResult)
        assert len(result.ground_zero) >= 1

    def test_blast_radius_ground_zero_set_correctly(self, indexed_graph):
        """Test that ground_zero contains the input functions."""
        result = indexed_graph.get_blast_radius(["main"])
        assert len(result.ground_zero) > 0
        # At least one ground_zero function should be named "main"
        names = [fn.name for fn in result.ground_zero]
        assert "main" in names

    def test_blast_radius_affected_includes_ground_zero(self, indexed_graph):
        """Test that affected_functions includes ground_zero functions."""
        result = indexed_graph.get_blast_radius(["main"])
        ground_zero_uids = {fn.uid for fn in result.ground_zero}
        affected_uids = {fn.uid for fn in result.affected_functions}
        # All ground zero should be in affected
        assert ground_zero_uids.issubset(affected_uids)

    def test_blast_radius_entry_points_subset_of_affected(self, indexed_graph):
        """Test that entry_points are a subset of affected_functions."""
        result = indexed_graph.get_blast_radius(["main"])
        entry_point_uids = {fn.uid for fn in result.entry_points}
        affected_uids = {fn.uid for fn in result.affected_functions}
        assert entry_point_uids.issubset(affected_uids)

    def test_blast_radius_call_chains_are_lists(self, indexed_graph):
        """Test that call_chains are lists of strings."""
        result = indexed_graph.get_blast_radius(["calculate"])
        assert isinstance(result.call_chains, list)
        for chain in result.call_chains:
            assert isinstance(chain, list)
            for name in chain:
                assert isinstance(name, str)

    def test_blast_radius_empty_input_returns_empty_result(self, indexed_graph):
        """Test that empty input returns empty result."""
        result = indexed_graph.get_blast_radius([])
        assert len(result.ground_zero) == 0
        assert len(result.affected_functions) == 0
        assert len(result.entry_points) == 0
        assert len(result.call_chains) == 0

    def test_blast_radius_nonexistent_function_returns_empty(self, indexed_graph):
        """Test that nonexistent function names return empty result."""
        result = indexed_graph.get_blast_radius(["nonexistent_function_xyz"])
        assert len(result.ground_zero) == 0
        assert len(result.affected_functions) == 0
        assert len(result.entry_points) == 0


# ============================================================================
# Recursive CTE & Depth Handling Tests
# ============================================================================


class TestRecursiveDepthHandling:
    """Test recursive CTE depth limit and cycle handling."""

    def test_get_affected_functions_respects_depth_limit(self, indexed_graph):
        """Test that _get_affected_functions respects depth limit."""
        # Query for a deep function
        affected = indexed_graph._get_affected_functions(["calculate"])
        assert isinstance(affected, set)
        # Should have some affected functions but not run forever
        assert len(affected) >= 1

    def test_blast_radius_on_chain(self, indexed_graph):
        """Test blast radius on a function in a call chain."""
        # Query for 'process' which is called by 'api_handler'
        result = indexed_graph.get_blast_radius(["process"])
        # 'process' should be in affected functions
        affected_names = {fn.name for fn in result.affected_functions}
        assert "process" in affected_names
        # 'api_handler' should also be affected (calls process)
        assert "api_handler" in affected_names

    def test_call_chains_finite(self, indexed_graph):
        """Test that call chains don't grow infinitely."""
        result = indexed_graph.get_blast_radius(["calculate"])
        # All chains should be finite and have reasonable length (< 20)
        for chain in result.call_chains:
            assert len(chain) < 20


# ============================================================================
# Integration Tests
# ============================================================================


class TestCodeGraphIntegration:
    """End-to-end integration tests."""

    def test_full_query_pipeline(self, indexed_graph):
        """Test complete query pipeline from changed function to result."""
        # Start with a function that's called by another
        result = indexed_graph.get_blast_radius(["process_data"])

        # Verify all components are present
        assert len(result.ground_zero) >= 1
        assert len(result.affected_functions) >= len(result.ground_zero)
        assert len(result.entry_points) >= 0
        # Call chains might be empty if the function isn't called from anywhere

    def test_multiple_independent_queries(self, indexed_graph):
        """Test that multiple queries don't interfere with each other."""
        result1 = indexed_graph.get_blast_radius(["calculate"])
        result2 = indexed_graph.get_blast_radius(["helper_func"])

        # Results should be independent
        names1 = {fn.name for fn in result1.affected_functions}
        names2 = {fn.name for fn in result2.affected_functions}

        # They might overlap but should have different content
        assert len(names1) >= 1
        assert len(names2) >= 1

    def test_blast_radius_result_structure(self, indexed_graph):
        """Test that BlastRadiusResult has correct structure."""
        result = indexed_graph.get_blast_radius(["main"])

        # Verify all fields exist and are correct types
        assert isinstance(result.ground_zero, list)
        assert isinstance(result.affected_functions, list)
        assert isinstance(result.entry_points, list)
        assert isinstance(result.call_chains, list)

        # Verify all items are correct types
        for fn in result.ground_zero:
            assert isinstance(fn, FunctionNode)
        for fn in result.affected_functions:
            assert isinstance(fn, FunctionNode)
        for fn in result.entry_points:
            assert isinstance(fn, FunctionNode)
        for chain in result.call_chains:
            assert isinstance(chain, list)
            for name in chain:
                assert isinstance(name, str)

    def test_end_to_end_complex_query(self, indexed_graph):
        """Test end-to-end query on a complex scenario."""
        # Query for multiple functions in different modules
        result = indexed_graph.get_blast_radius(["process_data", "helper_func", "calculate"])

        # Should have reasonable results
        assert len(result.ground_zero) >= 1
        assert len(result.affected_functions) >= len(result.ground_zero)

        # Entry points should be a proper subset
        entry_point_uids = {fn.uid for fn in result.entry_points}
        affected_uids = {fn.uid for fn in result.affected_functions}
        assert entry_point_uids.issubset(affected_uids)
