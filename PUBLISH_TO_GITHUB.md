# Publish this project to GitHub

Target account: **alexanderwchristian**
Repository name: **sec-filing-intelligence-agent**

## Fastest reliable way

1. Go to https://github.com/new while signed in as `alexanderwchristian`.
2. Set repository name to `sec-filing-intelligence-agent`, visibility to **Public**.
3. Do **not** initialize with a README, .gitignore, or license; those are already in this project.
4. Unzip the downloadable project to your computer, open a terminal in its folder, and run:

```bash
git init
git add .
git commit -m "Build SEC filing intelligence prototype"
git branch -M main
git remote add origin https://github.com/alexanderwchristian/sec-filing-intelligence-agent.git
git push -u origin main
```

If Git requests authentication, follow GitHub's browser/sign-in prompts or use GitHub Desktop to publish the local repository. Do not paste access tokens into this chat.

5. Your repo will be at https://github.com/alexanderwchristian/sec-filing-intelligence-agent once you have pushed it.
6. On the repo page, set the description to:

> Evidence-first SEC 10-K risk-factor change detection, with verbatim citations, optional LLM interpretation, and transparent evaluation.

Recommended topics: `sec-edgar`, `fintech`, `financial-research`, `ai-agents`, `llm-evaluation`.

## Portfolio integrity

The repository is independently implemented. All included sample filings are fictional. The public project must not include employer source code, documents, screenshots, proprietary prompts, or claims of deployed production performance. Publish only the materials you have permission to share.

## Enable a no-install recruiter demo (recommended)

On GitHub, open **Settings → Pages**, choose **Deploy from a branch**, set branch **main** and folder **/docs**, and save. Once GitHub Pages publishes, the walkthrough will be available at:

https://alexanderwchristian.github.io/sec-filing-intelligence-agent/

This page is a clearly labeled, precomputed sample, not a hosted live SEC analysis service.
