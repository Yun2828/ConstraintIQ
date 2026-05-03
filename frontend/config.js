/**
 * Runtime configuration for Constraint IQ frontend.
 *
 * In production (Vercel) set the BACKEND_URL environment variable in your
 * Vercel project settings → Environment Variables.
 *
 * Vercel injects build-time env vars into static files only when you use a
 * framework (Next.js, etc.).  For a plain static site the simplest approach
 * is to replace the placeholder at build time using the vercel.json rewrite
 * or a build script.  We default to the Railway backend URL here; override
 * by setting window.BACKEND_URL before this script loads, or by editing this
 * file during CI.
 */

// Allow the deployment pipeline to inject the real URL via a simple sed/envsubst
// in the Vercel build command (see vercel.json).
window.CONSTRAINT_IQ_CONFIG = {
  backendUrl: window.__BACKEND_URL__ || "https://constraint-iq-backend.onrender.com",
};
