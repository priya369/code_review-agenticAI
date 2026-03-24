"""
Claude Code Reviewer for Terraform
Fetches changed .tf / .tfvars files and posts review comments on the PR.
"""

import os
import sys
import subprocess
import anthropic
from github import Github

# ─────────────────────────────────────────────
# TERRAFORM REVIEW RULES
# Edit this section to customise what Claude checks
# ─────────────────────────────────────────────
TERRAFORM_REVIEW_RULES = """
You are a senior Terraform / cloud-infrastructure reviewer. Review the code strictly
against the rules below. For every violation, output a comment block formatted as:

  SEVERITY: <CRITICAL|WARNING|INFO>
  LINE: <line number or "general">
  RULE: <rule name>
  ISSUE: <clear description>
  SUGGESTION: <concrete fix>

────────────────────────────────────────────
CRITICAL rules (block merge)
────────────────────────────────────────────
1.  No hard-coded secrets
    Passwords, API keys, private IPs, account IDs in plain text are CRITICAL.
    Use var.*, data sources, or secret manager references.

2.  No hard-coded AWS account IDs / project IDs
    Use data "aws_caller_identity" or variables instead.

3.  Public S3 buckets are forbidden
    acl = "public-read" or "public-read-write" without an explicit
    # APPROVED: PUBLIC comment is CRITICAL.

4.  Unrestricted security group rules
    ingress/egress with cidr_blocks = ["0.0.0.0/0"] on sensitive ports
    (22, 3389, 5432, 3306, 6379, 27017) is CRITICAL unless explicitly
    commented with justification.

5.  Encryption must be enabled
    S3 buckets must have server_side_encryption_configuration.
    RDS must have storage_encrypted = true.
    EBS volumes must have encrypted = true.

6.  Deletion protection on stateful resources
    RDS, Aurora, and CloudFront distributions must have
    deletion_protection = true in production workspaces.

7.  No terraform.tfvars with secrets committed
    .tfvars files must not contain real secret values; only placeholders.

────────────────────────────────────────────
WARNING rules (should fix before merge)
────────────────────────────────────────────
8.  All resources must have required tags
    Every resource should include at minimum: Name, Environment, Owner, ManagedBy = "terraform".

9.  Variables must have descriptions and types
    Every variable block needs description and type. No untyped variables.

10. Outputs must have descriptions
    Every output block needs a description.

11. Avoid latest AMI without pinning
    data "aws_ami" with most_recent = true should be pinned or documented.

12. Remote state backend required
    terraform backend must be configured (S3 + DynamoDB locking for AWS).
    Local backend is WARNING in any non-dev context.

13. Provider version constraints required
    All providers must pin versions with ~> or >= constraints.
    No open-ended version = "latest" or missing required_providers.

14. Lifecycle prevent_destroy on critical resources
    Databases, state buckets, and KMS keys should have
    lifecycle { prevent_destroy = true }.

15. count vs for_each
    Prefer for_each over count for resources identified by a key to
    avoid destructive plan changes on list reordering.

────────────────────────────────────────────
INFO rules (good-to-have)
────────────────────────────────────────────
16. Module sourcing
    Prefer versioned modules from a registry over inline resource blocks
    for standard infrastructure (VPC, EKS, RDS).

17. Sensitive variables
    Variables holding secrets should be marked sensitive = true.

18. moved blocks
    Use moved {} blocks instead of destroy+recreate when renaming resources.

19. Consistent naming convention
    Resource names should follow snake_case and include environment prefix.

20. depends_on overuse
    Explicit depends_on hides intent; prefer implicit dependencies where possible.
────────────────────────────────────────────

After all violations, output a concise SUMMARY section:
  SUMMARY:
  - Critical issues: N
  - Warnings: N
  - Info notes: N
  - Overall verdict: APPROVE | REQUEST_CHANGES | COMMENT
"""


def get_file_diff(filepath: str) -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "origin/main...HEAD", "--", filepath],
            capture_output=True, text=True, check=True
        )
        return result.stdout or ""
    except subprocess.CalledProcessError:
        return ""


def read_file(filepath: str) -> str:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def review_tf_file(client: anthropic.Anthropic, filepath: str) -> str:
    content = read_file(filepath)
    diff = get_file_diff(filepath)

    if not content:
        return f"⚠️ Could not read file: {filepath}"

    ext = os.path.splitext(filepath)[1]
    lang = "hcl" if ext in (".tf",) else "ini"

    prompt = f"""
{TERRAFORM_REVIEW_RULES}

────────────────────────────────────────────
FILE: {filepath}
────────────────────────────────────────────
FULL FILE CONTENT:
```{lang}
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
    changed_files = [
        f for f in changed_files_env.split()
        if f.endswith(".tf") or f.endswith(".tfvars")
    ]

    if not changed_files:
        print("No Terraform files changed.")
        return

    repo_name = os.environ["REPO_NAME"]
    pr_number = int(os.environ["PR_NUMBER"])

    client = anthropic.Anthropic(api_key=api_key)

    all_reviews = []
    has_critical = False

    for filepath in changed_files:
        print(f"Reviewing {filepath} ...")
        review = review_tf_file(client, filepath)
        all_reviews.append(f"## 🔍 Terraform Review: `{filepath}`\n\n{review}")
        if "CRITICAL" in review:
            has_critical = True

    verdict_emoji = "🔴" if has_critical else "🟡"
    header = (
        f"# {verdict_emoji} Claude Terraform Review\n\n"
        f"> Auto-generated by Claude. "
        f"{'**Critical issues found — please fix before merging.**' if has_critical else 'No critical issues found.'}\n\n"
        f"---\n\n"
    )

    comment_body = header + "\n\n---\n\n".join(all_reviews)

    if len(comment_body) > 65000:
        comment_body = comment_body[:65000] + "\n\n_...truncated. See Actions logs for full output._"

    post_pr_comment(repo_name, pr_number, comment_body)
    print("Terraform review posted.")

    if has_critical:
        sys.exit(1)


if __name__ == "__main__":
    main()
