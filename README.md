# Doruk Live

Render web service prototype:
- index.html: live/results UI
- server.py: Flask + Playwright + SQLite
- requirements.txt: dependencies

IMPORTANT: The first deployment is a connectivity/DOM extraction prototype. After it is live, inspect /health and the Render logs; then tighten the Nesine DOM selectors so the exact team/score/status fields are parsed reliably.
