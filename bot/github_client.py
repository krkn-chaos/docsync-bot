import os
from github import Github


def _get_github() -> Github:
    return Github(os.environ["GITHUB_TOKEN"])


def find_open_drift_issue(repo_name: str, label: str = "docs-drift") -> int | None:
    """Returns issue number of the first open docs-drift issue, or None."""
    repo = _get_github().get_repo(repo_name)
    for issue in repo.get_issues(state="open", labels=[label]):
        return issue.number
    return None


def get_open_drift_body(repo_name: str, label: str = "docs-drift") -> str:
    """Body of the open docs-drift issue, or "" if none. Used to preserve ticked
    checkboxes across runs."""
    num = find_open_drift_issue(repo_name, label)
    if num is None:
        return ""
    return _get_github().get_repo(repo_name).get_issue(num).body or ""


def create_or_update_drift_issue(repo_name: str, title: str, body: str) -> str:
    """Creates new drift issue or edits existing open one. Returns HTML URL."""
    g = _get_github()
    repo = g.get_repo(repo_name)
    existing = find_open_drift_issue(repo_name)
    if existing:
        issue = repo.get_issue(existing)
        issue.edit(title=title, body=body)
        return issue.html_url
    try:
        repo.get_label("docs-drift")
    except Exception:
        repo.create_label("docs-drift", "d93f0b")
    issue = repo.create_issue(title=title, body=body, labels=["docs-drift"])
    return issue.html_url
