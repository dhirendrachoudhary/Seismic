"""Unit tests for Phase 5 git diff parser."""

import pytest
import tempfile
from pathlib import Path

from src.blast_radius.git_diff import ChangedRange, GitDiffParser


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        # Initialize git repo
        import subprocess

        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )

        yield repo_path


# ============================================================================
# ChangedRange Tests
# ============================================================================


class TestChangedRange:
    """Test ChangedRange dataclass."""

    def test_creation(self):
        """Test basic ChangedRange creation."""
        cr = ChangedRange("file.py", [1, 2, 3])
        assert cr.file_path == "file.py"
        assert cr.lines == [1, 2, 3]

    def test_lines_sorted_in_post_init(self):
        """Test that lines are sorted in __post_init__."""
        cr = ChangedRange("file.py", [3, 1, 2])
        assert cr.lines == [1, 2, 3]

    def test_lines_deduplicated_in_post_init(self):
        """Test that duplicate lines are removed."""
        cr = ChangedRange("file.py", [1, 2, 2, 3, 1])
        assert cr.lines == [1, 2, 3]

    def test_frozen_immutable(self):
        """Test that ChangedRange is immutable."""
        cr = ChangedRange("file.py", [1, 2])
        with pytest.raises(AttributeError):
            cr.file_path = "other.py"

    def test_empty_lines_list(self):
        """Test ChangedRange with empty lines."""
        cr = ChangedRange("file.py", [])
        assert cr.lines == []


# ============================================================================
# Hunk Header Parsing Tests
# ============================================================================


class TestHunkHeaderParsing:
    """Test hunk header parsing."""

    def test_parse_hunk_header_basic(self):
        """Parse basic hunk header '@@ -10,3 +15,4 @@'."""
        lines = GitDiffParser._parse_hunk_header("@@ -10,3 +15,4 @@")
        assert lines == [15, 16, 17, 18]

    def test_parse_hunk_header_single_line(self):
        """Parse hunk header with single line '@@ -10 +15 @@'."""
        lines = GitDiffParser._parse_hunk_header("@@ -10 +15 @@")
        assert lines == [15]

    def test_parse_hunk_header_with_function_context(self):
        """Parse hunk header with function context '@@ -10,3 +15,4 @@ def func():'."""
        lines = GitDiffParser._parse_hunk_header("@@ -10,3 +15,4 @@ def func():")
        assert lines == [15, 16, 17, 18]

    def test_parse_hunk_header_new_file_start_of_file(self):
        """Parse hunk header at start of new file '@@ -0,0 +1,5 @@'."""
        lines = GitDiffParser._parse_hunk_header("@@ -0,0 +1,5 @@")
        assert lines == [1, 2, 3, 4, 5]

    def test_parse_hunk_header_large_range(self):
        """Parse hunk header with large line range."""
        lines = GitDiffParser._parse_hunk_header("@@ -100,50 +200,60 @@")
        assert len(lines) == 60
        assert lines == list(range(200, 260))

    def test_parse_hunk_header_invalid_returns_empty(self):
        """Invalid hunk header returns empty list."""
        lines = GitDiffParser._parse_hunk_header("invalid line")
        assert lines == []


# ============================================================================
# Git Diff Parsing Tests
# ============================================================================


class TestGitDiffParsing:
    """Test git diff parsing."""

    def test_parse_single_file_with_changes(self, temp_git_repo):
        """Parse diff for single file with multiple hunks."""
        # Create and commit initial file
        file_path = temp_git_repo / "test.py"
        file_path.write_text("line1\nline2\nline3\n")

        import subprocess

        subprocess.run(
            ["git", "add", "test.py"], cwd=temp_git_repo, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )

        # Modify file
        file_path.write_text("modified1\nline2\nmodified3\n")

        parser = GitDiffParser(str(temp_git_repo))
        changed = parser.get_changed_ranges()

        assert len(changed) == 1
        assert changed[0].file_path.endswith("test.py")
        assert 1 in changed[0].lines  # First line changed
        assert 3 in changed[0].lines  # Third line changed

    def test_parse_multiple_files(self, temp_git_repo):
        """Parse diff with changes across multiple files."""
        # Create and commit initial files
        file1 = temp_git_repo / "file1.py"
        file2 = temp_git_repo / "file2.py"
        file1.write_text("content1\n")
        file2.write_text("content2\n")

        import subprocess

        subprocess.run(
            ["git", "add", "."], cwd=temp_git_repo, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )

        # Modify both files
        file1.write_text("modified1\n")
        file2.write_text("modified2\n")

        parser = GitDiffParser(str(temp_git_repo))
        changed = parser.get_changed_ranges()

        assert len(changed) == 2
        file_names = [c.file_path for c in changed]
        assert any("file1.py" in fn for fn in file_names)
        assert any("file2.py" in fn for fn in file_names)

    def test_parse_empty_diff_returns_empty_list(self, temp_git_repo):
        """No changes: return empty list."""
        # Create and commit file
        file_path = temp_git_repo / "test.py"
        file_path.write_text("content\n")

        import subprocess

        subprocess.run(
            ["git", "add", "test.py"], cwd=temp_git_repo, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )

        # No changes made
        parser = GitDiffParser(str(temp_git_repo))
        changed = parser.get_changed_ranges()

        assert changed == []

    def test_parse_new_file(self, temp_git_repo):
        """New file: all lines treated as changed."""
        # Create new file (not yet staged)
        file_path = temp_git_repo / "new_file.py"
        file_path.write_text("line1\nline2\nline3\n")

        # Stage it
        import subprocess

        subprocess.run(
            ["git", "add", "new_file.py"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )

        # Create new file
        new_file = temp_git_repo / "another_new.py"
        new_file.write_text("new1\nnew2\n")

        # Stage it
        subprocess.run(
            ["git", "add", "another_new.py"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )

        parser = GitDiffParser(str(temp_git_repo))
        changed = parser.get_changed_ranges()

        # Diff against HEAD (which doesn't have the new file)
        assert len(changed) >= 1

    def test_not_a_git_repo_returns_empty(self, temp_git_repo):
        """Not a git repo: return empty list (no crash)."""
        not_a_repo = tempfile.TemporaryDirectory()
        parser = GitDiffParser(not_a_repo.name)
        changed = parser.get_changed_ranges()
        assert changed == []
        not_a_repo.cleanup()

    def test_parser_creates_absolute_paths(self, temp_git_repo):
        """Verify that ChangedRange file_path is absolute."""
        # Create and commit file
        file_path = temp_git_repo / "test.py"
        file_path.write_text("content\n")

        import subprocess

        subprocess.run(
            ["git", "add", "test.py"], cwd=temp_git_repo, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )

        # Modify file
        file_path.write_text("modified\n")

        parser = GitDiffParser(str(temp_git_repo))
        changed = parser.get_changed_ranges()

        assert len(changed) == 1
        # Path should be absolute
        assert Path(changed[0].file_path).is_absolute()


# ============================================================================
# Integration Tests
# ============================================================================


class TestGitDiffIntegration:
    """End-to-end git diff parsing tests."""

    def test_diff_parsing_consistency(self, temp_git_repo):
        """Test that parsing is consistent across multiple calls."""
        # Setup repo
        file_path = temp_git_repo / "test.py"
        file_path.write_text("line1\nline2\nline3\n")

        import subprocess

        subprocess.run(
            ["git", "add", "test.py"], cwd=temp_git_repo, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )

        # Make changes
        file_path.write_text("modified1\nline2\nmodified3\n")

        parser = GitDiffParser(str(temp_git_repo))
        result1 = parser.get_changed_ranges()
        result2 = parser.get_changed_ranges()

        # Results should be the same
        assert result1 == result2

    def test_realistic_python_file_changes(self, temp_git_repo):
        """Test with realistic Python code changes."""
        file_path = temp_git_repo / "example.py"
        file_path.write_text(
            """def func_a():
    return 1

def func_b():
    return 2
"""
        )

        import subprocess

        subprocess.run(
            ["git", "add", "example.py"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True,
        )

        # Modify func_a (line 2) and add a new function
        file_path.write_text(
            """def func_a():
    return 10

def func_b():
    return 2

def func_c():
    return 3
"""
        )

        parser = GitDiffParser(str(temp_git_repo))
        changed = parser.get_changed_ranges()

        assert len(changed) == 1
        # Line 2 (modified return value) and lines 7-8 (new function)
        assert 2 in changed[0].lines  # Modified line
        assert 7 in changed[0].lines or 8 in changed[0].lines  # New function
