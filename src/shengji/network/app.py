from fastapi import FastAPI

app = FastAPI(title="Shengji")


@app.get("/")
async def root() -> dict:
    return {"status": "ok", "game": "shengji"}
