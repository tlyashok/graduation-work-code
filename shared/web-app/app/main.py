"""FilmRec - основная веб-система."""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routers import auth, catalog, profile, moderator, admin

app = FastAPI(title="FilmRec")

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(profile.router)
app.include_router(moderator.router)
app.include_router(admin.router)
