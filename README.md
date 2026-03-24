# code_review-agenticAI
# Claude AI Code Reviewer — Airflow DAGs & Terraform

Automatically reviews every PR that touches DAG files or Terraform with a
structured, rule-based report posted as a PR comment.

---

## Quick Setup (5 minutes)

### 1. Add your Anthropic API key as a GitHub Secret

1. Go to **Settings → Secrets and variables → Actions** in your repo
2. Click **New repository secret**
3. Name: `ANTHROPIC_API_KEY`
4. Value: your key from https://console.anthropic.com

### 2. Copy files into your repo

```
your-repo/
├── .github/
│   ├── workflows/
│   │   └── claude-code-review.yml   ← GitHub Actions workflow
│   ├── scripts/
│   │   ├── review_dags.py           ← DAG reviewer
│   │   └── review_terraform.py      ← Terraform reviewer
│   └── review_rules.yml             ← Toggle rules on/off here
├── dags/                            ← your Airflow DAGs
└── terraform/                       ← your Terraform code
```

### 3. Adjust folder paths (if needed)

In `claude-code-review.yml`, the `paths:` triggers default to:
- `dags/**/*.py`
- `terraform/**/*.tf` and `terraform/**/*.tfvars`

Change these to match your repo structure.

---

## How it Works

1. A PR is opened / updated with changes to DAG or Terraform files.
2. GitHub Actions detects the changed files.
3. Each file is sent to Claude with the relevant rule set.
4. Claude returns a structured report:
   - **CRITICAL** — fails the CI check (blocks merge if branch protection is on)
   - **WARNING** — should be fixed before merge
   - **INFO** — suggestions / best practices
5. The full report is posted as a PR comment.

---

## Customising Rules

Open `.github/review_rules.yml` and toggle `enabled: true/false` per rule, or
add new rules. Then edit the matching prompt in:
- `.github/scripts/review_dags.py` → `DAG_REVIEW_RULES` string
- `.github/scripts/review_terraform.py` → `TERRAFORM_REVIEW_RULES` string

---

## Branch Protection (recommended)

To enforce CRITICAL blocks:

1. **Settings → Branches → Add rule** for `main`
2. Enable **Require status checks to pass**
3. Add `Review Airflow DAGs` and `Review Terraform` as required checks

---

## Cost Estimate

Each file review uses ~2 000–6 000 tokens (input + output).
At Claude Sonnet pricing that is roughly **$0.003–$0.01 per file**.
A typical 5-file PR costs well under $0.05.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Workflow not triggering | Check `paths:` in the workflow matches your folder names |
| `ModuleNotFoundError: anthropic` | The `pip install` step runs first — check Actions logs |
| No PR comment posted | Ensure `GITHUB_TOKEN` has `pull-requests: write` permission |
| Review truncated | Large files hit GitHub's 65 535-char comment limit; see Actions log for full output |
