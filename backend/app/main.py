from fastapi import FastAPI
from .db import init_pool, close_pool
from .routes import users, skills, user_skills, user_interests

def create_app() -> FastAPI:
    app = FastAPI(title="Skill Share Backend", version="0.1.0")

    # lifespan: initialize and close the psycopg2 pool
    @app.on_event("startup")
    def on_startup():
        init_pool(minconn=1, maxconn=10)

    @app.on_event("shutdown")
    def on_shutdown():
        close_pool()

    # routes
    app.include_router(users.router)
    app.include_router(skills.router)
    app.include_router(user_skills.router)
    app.include_router(user_interests.router) 

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app

app = create_app()