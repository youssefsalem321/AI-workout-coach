# Deploying Smart Workout Coach

Two things to know before you put it online:

1. **Storage is a SQLite file.** On free hosts the disk is wiped on restart/redeploy, so user data is **not durable**.
   For a portfolio demo that is fine; for real users move to an external database (Supabase, Turso, Neon).
2. **Anyone with the link can use your Groq key.** Set a per-session AI call limit (below) and keep the key in the host's secrets, never in the repo.

## Environment variables / secrets

| Name | Purpose | Example |
|---|---|---|
| `GROQ_API_KEY` | Enables AI mode (without it the app runs rule-based) | `gsk_...` |
| `GROQ_MODEL` | Override the model if the default is retired | `llama-3.3-70b-versatile` |
| `MAX_LLM_CALLS_PER_SESSION` | Cap AI calls per visitor session (0 = unlimited, for local use) | `20` |
| `REQUIRE_USER_CODE` | Force visitors to enter a private code, so each gets their own database | `1` |

Visitors who paste their own API key in the sidebar are not limited.

## Option A: Streamlit Community Cloud (easiest)

1. Push the project to a GitHub repo (`.env` and `data/*.db` are already in `.gitignore`).
2. share.streamlit.io -> New app -> pick the repo, branch, main file `app.py`.
3. App settings -> Secrets, paste:
   ```toml
   GROQ_API_KEY = "your_key"
   MAX_LLM_CALLS_PER_SESSION = "20"
   REQUIRE_USER_CODE = "1"
   ```
   (Secrets are also exposed as environment variables.)
4. Deploy. You get a public `*.streamlit.app` link for the README and your LinkedIn post.

The **Form check** tab needs `mediapipe`, which is heavy. It is optional: on Streamlit Cloud the tab shows a friendly
"install extra packages" message. To enable it there, append the lines of `requirements-form.txt` to `requirements.txt`
(first build is slow; if the build fails, keep it off for the hosted demo and show the feature in a screen recording).

## Option B: Hugging Face Spaces (Docker)

1. New Space -> SDK: **Docker**.
2. Put this at the very top of the Space's `README.md`:
   ```yaml
   ---
   title: Smart Workout Coach
   sdk: docker
   app_port: 8501
   ---
   ```
3. Push the project files to the Space repo. To include form analysis, add `ARG WITH_FORM=1` as the default in the Dockerfile.
4. Space settings -> Variables and secrets: add `GROQ_API_KEY` (secret) and the variables above.

## Option C: your own machine / VPS

```bash
docker build --build-arg WITH_FORM=1 -t smart-coach .
docker run -p 8501:8501 --env-file .env -v coach-data:/app/data smart-coach
```
The `-v coach-data:/app/data` volume keeps the database between restarts.

## Using it on your phone at the gym

Open the deployed link in Chrome/Safari -> menu -> **Add to Home Screen**. It then opens full-screen like an app.
(It is a responsive web app, not an installable PWA: no offline mode and no push notifications.)
