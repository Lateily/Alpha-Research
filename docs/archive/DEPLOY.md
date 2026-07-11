# AR Platform v9.0 — Vercel Deployment Guide

## Architecture Overview

```
Frontend (React/Vite)  →  /api/research (Vercel Serverless)  →  Claude API
     ↓                           ↓
 Static assets            Anthropic SDK
 (auto-deployed)         (API key in env)
```

## Step 1: Get Anthropic API Key

1. Go to https://console.anthropic.com
2. Sign up (this is separate from your claude.ai Max subscription)
3. Go to Settings → API Keys → Create Key
4. Copy the key (starts with `sk-ant-...`)
5. New accounts get $5 free credit — enough for ~200 research reports

**Note:** Claude Max plan (claude.ai) ≠ API access. The API has its own billing.

## Step 2: Set Up Vercel

1. Go to https://vercel.com and sign up with your GitHub account (Lateily)
2. Click "Add New → Project"
3. Import your `Alpha-Research` repository
4. In the configuration screen:
   - Framework Preset: **Vite**
   - Build Command: `npm run build`
   - Output Directory: `dist`
5. Click "Environment Variables" and add:
   - Name: `ANTHROPIC_API_KEY`
   - Value: `sk-ant-...` (your key from Step 1)
6. Click **Deploy**

## Step 3: Push Updated Code

Run these commands in your terminal:

```bash
cd ~/Desktop/Stock/ar-platform

# Stage all new and changed files
git add vercel.json api/research.js src/Dashboard.jsx package.json vite.config.js

# Commit
git commit -m "v9.0: Deep Research with Claude API + Vercel backend"

# Push
git push
```

Vercel will auto-detect the push and redeploy.

## Step 4: Verify

1. Your new URL will be: `https://alpha-research-xxx.vercel.app` (Vercel assigns a domain)
2. Open the site → Click the green "Deep" button in the top bar
3. Enter any ticker (e.g., `NVDA`, `688981.SH`, `9888.HK`)
4. Click "Generate Buy-Side Research"
5. Wait ~15 seconds — Claude generates a full 6-stage research report

## About GitHub Pages

The old GitHub Pages deployment (`Lateily.github.io/Alpha-Research/`) will still work for the static version. Vercel is the new primary deployment with API support.

If you want to disable GitHub Pages:
- Go to GitHub repo → Settings → Pages → Source → None

## File Structure

```
ar-platform/
├── api/
│   └── research.js          ← Vercel serverless function (calls Claude API)
├── src/
│   └── Dashboard.jsx         ← Frontend with DeepResearchPanel
├── vercel.json               ← Vercel config
├── vite.config.js            ← Updated (base: '/', dev proxy)
└── package.json              ← v2.0 with @anthropic-ai/sdk
```

## Local Development

```bash
# Terminal 1: Frontend
cd ~/Desktop/Stock/ar-platform
npm install          # installs @anthropic-ai/sdk
npm run dev          # starts Vite at localhost:5173

# The /api/research endpoint only works on Vercel (serverless).
# For local API testing, you would need vercel dev (optional).
```

## Cost Estimate

Each research report uses ~4K output tokens from Claude Sonnet.
- Cost: ~$0.06 per report
- $5 free credit = ~80 reports
- $20/month API budget = ~330 reports/month
