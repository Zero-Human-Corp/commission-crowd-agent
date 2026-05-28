# Syntaxis Labs Portfolio Website

## Overview

A simple, professional portfolio website for **Syntaxis Labs** — an independent commission-only B2B sales partnership. The site positions Syntaxis Labs as a sales partner for B2B SaaS, AI, automation, data, cybersecurity, and business services vendors.

## Purpose

This website supports the CommissionCrowd profile completion by providing:
- A public-facing presence vendors can review
- Clear positioning as a commission-only sales partner
- Specific industry focus and territory coverage
- Transparent sales motion and commission preferences

## Pages

| Page | File | Purpose |
|------|------|---------|
| Home | `index.html` | Hero section, industries, sales motion, territories, CTA |
| Commission-Only Sales | `commission-only-sales.html` | How the model works, process, what we don't do |
| For Vendors | `vendor-partnership.html` | Why partner, ideal vendor criteria, engagement process |
| Opportunities | `opportunity-preferences.html` | Preferred industries, territories, commission structure, sales strengths |
| CommissionCrowd Profile | `commissioncrowd-profile.html` | Platform-specific profile content, tags, categories |
| Contact | `contact.html` | Contact details, LinkedIn, CommissionCrowd links |

## Files

```
sites/syntaxis-labs/
├── index.html
├── commission-only-sales.html
├── vendor-partnership.html
├── opportunity-preferences.html
├── commissioncrowd-profile.html
├── contact.html
├── css/
│   └── styles.css
├── js/
│   └── (placeholder for future interactivity)
└── assets/
    └── (placeholder for images, logos)
```

## How to Preview Locally

### Option 1: Python HTTP Server (Recommended)

```bash
cd /home/ubuntu/projects/commission-crowd-agent/sites/syntaxis-labs
python3 -m http.server 8080
```

Then open: http://localhost:8080

### Option 2: Using the CLI Preview Tool

```bash
cd /home/ubuntu/projects/commission-crowd-agent
PYTHONPATH=src .venv/bin/python -m commission_crowd_agent.cli preview-site sites/syntaxis-labs
```

### Option 3: Using the Built-in `npx serve`

```bash
cd /home/ubuntu/projects/commission-crowd-agent/sites/syntaxis-labs
npx serve -l 8080
```

## How to Publish

### Option 1: Netlify Drop (Free, Fast)

1. Go to https://app.netlify.com/drop
2. Drag and drop the `sites/syntaxis-labs/` folder
3. Get a `.netlify.app` URL instantly
4. Optional: connect a custom domain later

### Option 2: GitHub Pages (Free, Version-Controlled)

1. Create a `syntaxis-labs` repo on GitHub
2. Push the `sites/syntaxis-labs/` contents to `gh-pages` branch
3. Enable GitHub Pages in repo settings
4. Site will be at `https://yourusername.github.io/syntaxis-labs/`

### Option 3: Vercel (Free, Fast)

1. Install Vercel CLI: `npm i -g vercel`
2. Run: `cd sites/syntaxis-labs && vercel --prod`
3. Follow prompts to deploy

### Option 4: Surge.sh (Free, Command-Line)

1. Install: `npm i -g surge`
2. Run: `cd sites/syntaxis-labs && surge`
3. Follow prompts

## Before Publishing Checklist

- [ ] Review all site copy with operator
- [ ] Add profile photo to `assets/photo.jpg`
- [ ] Add company logo to `assets/logo.png`
- [ ] Verify CommissionCrowd profile link is correct
- [ ] Confirm LinkedIn URL is correct
- [ ] Add Google Analytics (optional)
- [ ] Set up custom domain (optional)
- [ ] Test responsive layout on mobile devices
- [ ] Verify all internal links work

## Governance

- **Do not publish without operator approval.**
- **Do not add unverified claims, testimonials, or client names.**
- **Do not modify CommissionCrowd profile through this site.**
- This site is for positioning and credibility — not for live lead capture (yet).

## Site Copy Review

See: `/home/ubuntu/.hermes/syntaxis_labs_site_copy_review_20260528.md`

## Commission-Crowd Profile Alignment

This site supports the CommissionCrowd profile completion by serving as the **Website / Portfolio URL** field. Once published, update the CommissionCrowd profile with the live URL.

## Tech Stack

- **Pure HTML5** — no build step required
- **CSS3** — single stylesheet, mobile-responsive
- **No JavaScript** — lightweight and fast
- **No external dependencies** — self-contained

## License

© 2026 Syntaxis Labs. All rights reserved.
