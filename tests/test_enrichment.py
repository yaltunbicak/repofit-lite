"""Tests for enrichment — API mocked."""

from repofit.enrichment import _detect_ci, _detect_tests, _detect_tests_from_readme


def test_detect_ci_github_actions():
    """Should detect GitHub Actions workflows as CI."""
    files = [".github/workflows", "src", "README.md"]
    assert _detect_ci(files) is True


def test_detect_ci_bare_github_not_ci():
    """Bare .github dir should NOT be detected as CI (false positive fix)."""
    files = [".github", "src", "README.md"]
    assert _detect_ci(files) is False


def test_detect_ci_gitlab_ci():
    """Should detect .gitlab-ci.yml as CI."""
    files = [".gitlab-ci.yml", "src", "README.md"]
    assert _detect_ci(files) is True


def test_detect_ci_none():
    """Should return False when no CI indicators found."""
    files = ["src", "README.md", "setup.py"]
    assert _detect_ci(files) is False


def test_detect_tests_directory():
    """Should detect tests/ directory."""
    files = ["tests", "src", "README.md"]
    assert _detect_tests(files) is True


def test_detect_tests_jest():
    """Should detect jest.config."""
    files = ["jest.config.js", "src", "package.json"]
    assert _detect_tests(files) is True


def test_detect_tests_none():
    """Should return False when no test indicators found."""
    files = ["src", "README.md", "main.py"]
    assert _detect_tests(files) is False


def test_detect_ci_jenkinsfile():
    """Should detect Jenkinsfile."""
    files = ["Jenkinsfile", "src"]
    assert _detect_ci(files) is True


def test_detect_tests_spec_dir():
    """Should detect spec/ directory."""
    files = ["spec", "lib", "Gemfile"]
    assert _detect_tests(files) is True


# --- README-based test detection ---

def test_detect_tests_from_readme_pytest():
    """Should detect pytest mention in README."""
    readme = "## Development\nRun tests with `pytest tests/`"
    assert _detect_tests_from_readme(readme) is True


def test_detect_tests_from_readme_jest():
    """Should detect jest mention."""
    readme = "# Testing\nWe use jest for unit testing."
    assert _detect_tests_from_readme(readme) is True


def test_detect_tests_from_readme_none():
    """Should return False for README without test mentions."""
    readme = "# My Project\nThis is a cool project for doing things."
    assert _detect_tests_from_readme(readme) is False


def test_detect_tests_from_readme_empty():
    """Should handle None/empty README."""
    assert _detect_tests_from_readme(None) is False
    assert _detect_tests_from_readme("") is False
