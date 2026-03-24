"""
Claude Code Reviewer for Airflow DAGs
Fetches changed files and posts review comments on the PR.
"""

import os
import sys
import subprocess
import anthropic
from github import Github

# ─────────────────────────────────────────────
# AIRFLOW DAG REVIEW RULES
# Edit this section to customise what Claude checks
# ─────────────────────────────────────────────
DAG_REVIEW_RULES = """
You are a senior Airflow / data-engineering reviewer. Review the DAG code strictly
against the rules below. For every violation, output a comment block formatted as:

  SEVERITY: <CRITICAL|WARNING|INFO>
  LINE: <line number or "general">
  RULE: <rule name>
  ISSUE: <clear description>
  SUGGESTION: <concrete fix>

────────────────────────────────────────────
CRITICAL rules (block merge)
────────────────────────────────────────────
1.  NO top-level code execution
    DAGs must NOT run DB queries, API calls, or heavy logic at import time.
    Only lightweight variable assignments are allowed outside tasks.

2.  catchup must be explicit
    Every DAG must set catchup=False (or True with justification in a comment).
    Missing catchup= is a CRITICAL error.

3.  schedule_interval / schedule must be explicit
    Never rely on the default. Cron strings must be valid.

4.  No hard-coded credentials
    Passwords, tokens, secret keys in plain text are CRITICAL violations.
    Use Airflow Variables or Connections instead.

5.  start_date must be static
    start_date=datetime.now() or any dynamic expression is forbidden.
    Use a fixed date: datetime(2024, 1, 1).

6.  dag_id must be unique and match file name
    dag_id should equal the Python file name (without .py) or include a
    clear namespace prefix.

────────────────────────────────────────────
WARNING rules (should fix before merge)
────────────────────────────────────────────
7.  retries & retry_delay on every task
    Default args should include retries >= 1 and retry_delay >= timedelta(minutes=5).

8.  task timeout
    Long-running tasks must set execution_timeout.

9.  No bare except clauses
    Use specific exceptions; bare `except:` hides real errors.

10. SLA missing on critical DAGs
    DAGs tagged "critical" or "sla" should set sla on tasks or the DAG.

11. Email/Slack on_failure_callback
    Production DAGs should define on_failure_callback.

12. Avoid deprecated operators
    DummyOperator → EmptyOperator, PythonOperator with provide_context → use op_kwargs.

13. Doc strings required
    Every DAG file must have a module-level docstring explaining purpose,
    owner, and expected schedule.

────────────────────────────────────────────
INFO rules (good-to-have)
────────────────────────────────────────────
14. Tags recommended
    DAGs should include at least one tag for discoverability.

15. max_active_runs should be set
    Defaults can cause queue flooding; prefer max_active_runs=1 for most DAGs.

16. Idempotency note
    Tasks that write data should handle re-runs gracefully (upsert, truncate+insert, etc.).

17. Prefer TaskFlow API (@task decorator) for PythonOperator tasks.
────────────────────────────────────────────

After all violations, output a concise SUMMARY section:
  SUMMARY:
  - Critical issues: N
  - Warnings: N
  - Info notes: N
  - Overall verdict: APPROVE | REQUEST_CHANGES | COMMENT
"""


def get_file_diff(filepath: str) -> str:
    """Return the git diff for a single file."""
    try:
        result = subprocess.run(
            ["git", "diff", "origin/main...HEAD", "--", filepath],
            capture_output=True, text=True, check=True
        )
        return result.stdout or ""
    except subprocess.CalledProcessError:
        return ""


def read_file(filepath: str) -> str:
    """Read full file content."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def review_dag_file(client: anthropic.Anthropic, filepath: str) -> str:
    """Send DAG file to Claude for review and return the review text."""
    content = read_file(filepath)
    diff = get_file_diff(filepath)

    if not content:
        return f"⚠️ Could not read file: {filepath}"

    prompt = f"""
{DAG_REVIEW_RULES}

────────────────────────────────────────────
FILE: {filepath}
────────────────────────────────────────────
FULL FILE CONTENT:
```python
{content}
```

GIT DIFF (what changed in this PR):
```diff
{diff if diff else '(new file – no diff)'}
```

Now produce your review.
"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def post_pr_comment(repo_name: str, pr_number: int, body: str) -> None:
    """Post a comment on the GitHub PR."""
    token = os.environ["GITHUB_TOKEN"]
    g = Github(token)
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    pr.create_issue_comment(body)


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    changed_files_env = os.environ.get("CHANGED_FILES", "")
    changed_files = [f for f in changed_files_env.split() if f.endswith(".py")]

    if not changed_files:
        print("No DAG files changed.")
        return

    repo_name = os.environ["REPO_NAME"]
    pr_number = int(os.environ["PR_NUMBER"])

    client = anthropic.Anthropic(api_key=api_key)

    all_reviews = []
    has_critical = False

    for filepath in changed_files:
        print(f"Reviewing {filepath} ...")
        review = review_dag_file(client, filepath)
        all_reviews.append(f"## 🔍 DAG Review: `{filepath}`\n\n{review}")
        if "CRITICAL" in review:
            has_critical = True

    verdict_emoji = "🔴" if has_critical else "🟡"
    header = (
        f"# {verdict_emoji} Claude Airflow DAG Review\n\n"
        f"> Auto-generated by Claude. "
        f"{'**Critical issues found — please fix before merging.**' if has_critical else 'No critical issues found.'}\n\n"
        f"---\n\n"
    )

    comment_body = header + "\n\n---\n\n".join(all_reviews)

    # Trim if too long for GitHub (65535 char limit)
    if len(comment_body) > 65000:
        comment_body = comment_body[:65000] + "\n\n_...truncated. See Actions logs for full output._"

    post_pr_comment(repo_name, pr_number, comment_body)
    print("DAG review posted.")

    if has_critical:
        sys.exit(1)  # Fail the check on critical issues


if __name__ == "__main__":
    main()
