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

   - `PORT`: 8080 (set by Railway automatically)
   - `RAILWAY_STATIC_URL`: Your Railway deployment URL (e.g., https://your-app-name.up.railway.app)

3. Push your code to a Git repository and connect it to Railway for deployment.

4. The deployment will use the `railway.toml` file to determine how to build and run the application.

## Accessing Multiple Nodes

This setup runs multiple blockchain nodes within a single Railway deployment. Each node is accessible via a different URL path:

- Node 0 (Bootstrap node): https://your-app-name.up.railway.app/node0

  - View blockchain: https://your-app-name.up.railway.app/node0/chain
  - Mine blocks: https://your-app-name.up.railway.app/node0/mine
  - View pending transactions: https://your-app-name.up.railway.app/node0/pending_tx

- Node 1: https://your-app-name.up.railway.app/node1

  - View blockchain: https://your-app-name.up.railway.app/node1/chain
  - Mine blocks: https://your-app-name.up.railway.app/node1/mine
  - View pending transactions: https://your-app-name.up.railway.app/node1/pending_tx

- Node 2: https://your-app-name.up.railway.app/node2
  - View blockchain: https://your-app-name.up.railway.app/node2/chain
  - Mine blocks: https://your-app-name.up.railway.app/node2/mine
  - View pending transactions: https://your-app-name.up.railway.app/node2/pending_tx

The home page at https://your-app-name.up.railway.app/ shows a list of all available nodes.

Note: Railway uses the PORT environment variable internally, which will override your FLASK_RUN_PORT setting.
