from app.main import app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", port=8000, reload=True)
