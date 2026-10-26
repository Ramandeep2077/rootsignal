from fastapi import FastAPI

app = FastAPI(title="oncall-agent")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
