import os


def main() -> None:
    role = os.getenv("RAILWAY_SERVICE_ROLE", "api").strip().lower()

    if role == "mcp":
        from server.server import run_mcp

        run_mcp()
        return

    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
