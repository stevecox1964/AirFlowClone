"""Entry point: `python -m airflowclone.main` or `uvicorn airflowclone.api:app`."""
import uvicorn


def main() -> None:
    uvicorn.run(
        "airflowclone.api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
