# Running BlockChat with Docker

## Prerequisites

- Docker Desktop running
- cd blockchain-scratchuick Start

1. **Build and start all containers**:

```bash
docker-compose up --build
```

## Stopping the System

To stop all containers:

```bash
docker-compose down
```

To stop and remove all data (volumes):

```bash
docker-compose down -v
```

# Deployment to Railway

## Prerequisites

- Railway CLI installed (optional)
- A Railway account

## Deployment Steps

1. Create a new project on Railway dashboard.

2. Add the required environment variables in Railway dashboard:

   - `FLASK_RUN_PORT`: 8000 (Railway will override this with PORT)
   - `HTTP_NODE_ADDRESS`: Your Railway deployment URL (e.g., https://your-app-name.railway.app)
   - `KADEMLIA_PORT`: 5678
   - `DATA_FILE`: chain.json

3. Push your code to a Git repository and connect it to Railway for deployment.

4. The deployment will use the `railway.toml` and `Procfile` files to determine how to build and run the application.

Note: Railway uses the PORT environment variable internally, which will override your FLASK_RUN_PORT setting.
