from fastapi import FastAPI

app = FastAPI(title="NetScope API")


@app.get("/api/health")
def health():
    return {"status": "ok"}
