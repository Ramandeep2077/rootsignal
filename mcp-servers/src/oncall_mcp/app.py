from fastapi import FastAPI

app = FastAPI(title="oncall-mcp")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
