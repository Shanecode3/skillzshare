from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .db import init_pool, close_pool
from .config import settings
from .routes import users, skills, user_skills, user_interests, collab_requests, messages, match_candidates, auth

def create_app() -> FastAPI:
    app = FastAPI(title="Skill Share Backend", version="0.1.0")

    # lifespan: initialize and close the psycopg2 pool
    @app.on_event("startup")
    def on_startup():
        init_pool(minconn=1, maxconn=10)

    @app.on_event("shutdown")
    def on_shutdown():
        close_pool()

    origins = [o.strip() for o in settings.cors_origins.split(",")] if settings.cors_origins else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5500", "*"] ,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # routes
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(skills.router)
    app.include_router(user_skills.router)
    app.include_router(user_interests.router)
    app.include_router(collab_requests.router) 
    app.include_router(messages.router)            
    app.include_router(match_candidates.router)     

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app

app = create_app()