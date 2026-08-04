from unittest.mock import MagicMock, patch
from bot.github_client import create_or_update_drift_issue, find_open_drift_issue


def _mock_github(issues: list[int | None]):
    """Returns a patched Github() that yields mock issues for get_issues()."""
    mock_g = MagicMock()
    mock_repo = MagicMock()
    mock_g.get_repo.return_value = mock_repo
    if issues:
        mock_issue = MagicMock()
        mock_issue.number = issues[0]
        mock_issue.html_url = f"https://github.com/test/repo/issues/{issues[0]}"
        mock_repo.get_issues.return_value = iter([mock_issue])
    else:
        mock_repo.get_issues.return_value = iter([])
    return mock_g, mock_repo


def test_find_open_drift_issue_returns_number_when_exists():
    mock_g, _ = _mock_github([42])
    with patch("bot.github_client._get_github", return_value=mock_g):
        result = find_open_drift_issue("owner/repo")
    assert result == 42


def test_find_open_drift_issue_returns_none_when_absent():
    mock_g, _ = _mock_github([])
    with patch("bot.github_client._get_github", return_value=mock_g):
        result = find_open_drift_issue("owner/repo")
    assert result is None


def test_create_or_update_edits_existing_issue():
    """When there is already an open drift issue, it should be edited and not create a new one."""
    mock_g, mock_repo = _mock_github([42])
    mock_existing = MagicMock()
    mock_existing.html_url = "https://github.com/owner/repo/issues/42"
    mock_repo.get_issue.return_value = mock_existing

    with patch("bot.github_client._get_github", return_value=mock_g):
        url = create_or_update_drift_issue("owner/repo", "new title", "new body")

    mock_existing.edit.assert_called_once_with(title="new title", body="new body")
    mock_repo.create_issue.assert_not_called()
    assert url == "https://github.com/owner/repo/issues/42"


def test_create_or_update_creates_new_issue_when_none_exists():
    """When no drift issue exists, create a fresh one with the docs-drift label."""
    mock_g, mock_repo = _mock_github([])
    mock_new = MagicMock()
    mock_new.html_url = "https://github.com/owner/repo/issues/99"
    mock_repo.create_issue.return_value = mock_new

    with patch("bot.github_client._get_github", return_value=mock_g):
        url = create_or_update_drift_issue("owner/repo", "title", "body")

    mock_repo.create_issue.assert_called_once_with(
        title="title", body="body", labels=["docs-drift"]
    )
    assert url == "https://github.com/owner/repo/issues/99"
