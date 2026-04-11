#!/bin/bash

# Configuration (can be overridden via env or positional args)
MODULE_NAME="${1:-${MODULE_NAME:-HostApp}}"
CONTAINER_NAME="${2:-${CONTAINER_NAME:-backend}}"
SCRIPT_PATH="app.create_superuser_cli"

echo "Creating Superadmin for $MODULE_NAME..."

# Check if backend container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Error: Backend container '$CONTAINER_NAME' is not running."
    echo "Please start the services first: docker compose up -d"
    exit 1
fi

# Execute script inside container
docker exec -it $CONTAINER_NAME python -m $SCRIPT_PATH "$@"
