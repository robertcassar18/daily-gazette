# Daily News Digest

A GitHub Pages news site generated daily with Gemini and Google Search grounding.

## Required secret

Add this repository secret:

`GEMINI_API_KEY`

Optional repository variable:

`GEMINI_MODEL` (optional; defaults to the auto-detected latest free-tier Gemini model)

## GitHub Pages

1. Enable **Settings → Pages → Deploy from a branch**.
2. Select the default branch and the repository root (`/`).
3. Add your custom domain in the Pages settings.
4. For a subdomain, add a DNS CNAME pointing to `YOUR-USERNAME.github.io`.
5. For an apex domain, use GitHub's current Pages A records.
6. Enable HTTPS after DNS has propagated.

The workflow commits `index.html` and `daily-YYYY-MM-DD.html` to the selected branch. `index.html` is rebuilt after each edition and contains a native calendar picker. The newest available edition is loaded by default; unavailable dates are rejected.

## Schedule

The workflow runs at 08:00 and 09:00 UTC and proceeds only when the local time in Europe/Malta is 10:00. This accounts for Malta's daylight-saving time. GitHub may delay scheduled jobs by a few minutes. `workflow_dispatch` runs immediately and bypasses the time check.

## First run

Run the workflow manually from **Actions → Generate daily news digest → Run workflow**. The first successful run creates the first daily HTML file and `index.html`.
