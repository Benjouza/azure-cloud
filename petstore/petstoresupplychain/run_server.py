"""Local dev entry point. Loads .env then starts server."""
from dotenv import load_dotenv
load_dotenv()

from src.server import app  # noqa: E402

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8088)
