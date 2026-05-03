# Deployment Guide — Constraint IQ

**Stack**: Render (backend, free) + Vercel (frontend, free)

---

## Prerequisites

- GitHub account with this repo pushed
- [Render account](https://render.com) — free, no credit card needed
- [Vercel account](https://vercel.com) — free

---

## Step 1 — Push to GitHub

```bash
git add .
git commit -m "ready for deployment"
git push origin main
```

---

## Step 2 — Deploy Backend to Render

1. Go to [dashboard.render.com](https://dashboard.render.com) → **New** → **Web Service**
2. Connect your GitHub repo
3. Render detects `render.yaml` automatically — click **Apply**
4. It will create a service called `constraint-iq-backend`
5. Wait for the build to finish (~3-5 minutes first time)
6. Your backend URL will be: `https://constraint-iq-backend.onrender.com`

**Test it:**
```bash
curl https://constraint-iq-backend.onrender.com/health
# → {"status":"ok"}
```

> **Note**: On the free tier, the service sleeps after 15 minutes of inactivity.
> The first request after sleeping takes ~30 seconds to wake up. Subsequent
> requests are fast.

---

## Step 3 — Set the backend URL in the frontend

Edit `frontend/config.js`:

```js
window.CONSTRAINT_IQ_CONFIG = {
  backendUrl: "https://constraint-iq-backend.onrender.com",
};
```

Commit and push:
```bash
git add frontend/config.js
git commit -m "set Render backend URL"
git push origin main
```

---

## Step 4 — Deploy Frontend to Vercel

**Option A — Vercel CLI:**
```bash
npm i -g vercel
vercel --prod
```
When prompted:
- Root directory: `.`
- Framework preset: **Other**
- Build command: *(leave blank — press Enter)*
- Output directory: `frontend`

**Option B — Vercel dashboard:**
1. Go to [vercel.com/new](https://vercel.com/new) → Import your GitHub repo
2. **Framework Preset**: Other
3. **Output Directory**: `frontend`
4. **Build Command**: *(leave blank)*
5. Click **Deploy**

Your frontend URL will be: `https://constraint-iq.vercel.app`

---

## Step 5 — Lock down CORS (optional but recommended)

Go to Render → your service → **Environment** → edit `ALLOWED_ORIGINS`:

```
ALLOWED_ORIGINS=https://constraint-iq.vercel.app
```

Render redeploys automatically.

---

## Done

Open your Vercel URL, upload a `.dxf` or `.pdf` file, and the analysis runs
against the Render backend.

---

## Local Development

**Backend:**
```bash
cd backend
pip install -r requirements.txt
pip install -e .
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
python3 -m http.server 3000
# open http://localhost:3000
```

`frontend/config.js` defaults to `http://localhost:8000` so local dev works
without any changes.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| First request takes 30s | Expected — Render free tier cold start. Subsequent requests are fast. |
| CORS error in browser console | Check `ALLOWED_ORIGINS` in Render env vars matches your Vercel URL exactly |
| `{"detail": "Unsupported file type"}` | Upload a `.dxf`, `.dwg`, or `.pdf` file |
| Build fails on Render | Check build logs — WeasyPrint system deps are in the Dockerfile |
| Vercel shows blank page | Make sure Output Directory is set to `frontend` in Vercel settings |
