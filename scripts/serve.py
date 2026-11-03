import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "sales_intelligence.api:create_app",
        factory=True,
        host=os.environ.get("SALES_BIND", "127.0.0.1"),
        port=8000,
        workers=1,
    )
