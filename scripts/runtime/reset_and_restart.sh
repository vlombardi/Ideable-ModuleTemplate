
#!/bin/bash
set -e

# Parse command line arguments
FORCE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--force)
            FORCE=true
            shift
            ;;
        *)
            echo "Unknown option $1"
            exit 1
            ;;
    esac
done

# DANGER WARNING AND CONFIRMATION
if [ "$FORCE" = false ]; then
    cat <<EOF
WARNING: This script will perform a FULL RESET of your stack.
ALL configurations, database data, and broker topic contents will be LOST.
This operation is IRREVERSIBLE.

Are you sure you want to continue? Type 'YES' to proceed:
EOF
    read -r CONFIRM
    if [ "$CONFIRM" != "YES" ]; then
      echo -e "${RED}Aborted by user. No changes made.${NC}"
      exit 1
    fi
fi

# Load environment variables
if [ -f ./base_services/.env ]; then
  source ./base_services/.env
fi

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to detect if running on Raspberry Pi
is_raspberry_pi() {
    if [ -f /proc/device-tree/model ]; then
        if grep -q "Raspberry Pi" /proc/device-tree/model; then
            return 0
        fi
    fi
    return 1
}

# Check if running on Raspberry Pi
if is_raspberry_pi; then
    echo -e "${YELLOW}Detected Raspberry Pi hardware. Using RPi4 optimized configuration.${NC}"
    DOCKER_COMPOSE_FILE="docker-compose-rpi4.yml"
    # Set lower memory limits for RPi
    export COMPOSE_PARALLEL_LIMIT=1
    export COMPOSE_HTTP_TIMEOUT=120
else
    echo -e "${GREEN}Using standard configuration.${NC}"
    DOCKER_COMPOSE_FILE="docker-compose.yml"
fi





# Stop base containers and shelly integration
if [ -f ./base_services/stop_base_services.sh ]; then
  echo ""
  echo "**************************"
  echo "* Stopping base services *"
  echo "**************************"
  # During reset, we want to remove volumes as well, so we call stop_base_services.sh with -v option
  (cd ./base_services && ./stop_base_services.sh --force -v)
else
  echo "Warning: ./base_services/stop_base_services.sh not found."
fi

# Check if any Base Service containers are still running and remove them
echo ""
echo "*************************************************"
echo "* Checking for leftover Base Service containers *"
echo "*************************************************"
echo "Stopping and removing leftover containers..."

if docker stop broker 2>/dev/null; then
  docker rm broker
else
  echo No leftover broker container found
fi

if docker stop timescale 2>/dev/null; then
  docker rm timescale
else
  echo No leftover timescale container found
fi

if docker stop redpanda 2>/dev/null; then
  docker rm redpanda
else
  echo No leftover redpanda container found
fi

if docker stop flink-jobmanager 2>/dev/null; then
  docker rm flink-jobmanager
else
  echo No leftover flink-jobmanager container found
fi

if docker stop flink-taskmanager 2>/dev/null; then
  docker rm flink-taskmanager
else
  echo No leftover flink-taskmanager container found
fi

if docker stop flink-job-compiler 2>/dev/null; then
  docker rm flink-job-compiler
else
  echo No leftover flink-job-compiler container found
fi

if docker stop flink-job-submitter 2>/dev/null; then
  docker rm flink-job-submitter
else
  echo No leftover flink-job-submitter container found
fi



if [ -f ./integrations/shelly/stop_shelly_integration.sh ]; then
  echo ""
  echo "*******************************"
  echo "* Stopping Shelly integration *"
  echo "*******************************"
  (cd ./integrations/shelly && ./stop_shelly_integration.sh --force)
  
  # Check if any Shelly containers are still running and remove them
  echo ""
  echo "*******************************************"
  echo "* Checking for leftover Shelly containers *"
  echo "*******************************************"
  SHELLY_CONTAINERS=$(docker ps -aq -f name=shelly)
  if [ -n "$SHELLY_CONTAINERS" ]; then
    echo "Found leftover Shelly containers:"
    docker ps -a -f name=shelly --format "table {{.Names}}\t{{.Status}}"
    echo ""
    # In force mode, automatically remove leftover containers
    echo "Stopping and removing leftover containers..."
    docker stop $SHELLY_CONTAINERS
    docker rm $SHELLY_CONTAINERS
    echo "Containers removed successfully."
  else
    echo "No leftover Shelly containers found."
  fi
else
  echo "Warning: ./integrations/shelly/stop_shelly_integration.sh not found."
fi

echo ""
echo "************************"
echo "* Configuring data folder *"
echo "************************"
# Load environment variables again to ensure we have the latest values
if [ -f ./base_services/.env ]; then
  source ./base_services/.env
fi

# Set default paths based on whether we're on RPi4 or not
if is_raspberry_pi; then
  # On RPi4, use the standard path if not set
  DATA_PATH="${DATA_FOLDER:-/home/pi/redpanda_flink_timescale/data}"
else
  # On other systems, use relative path
  DATA_PATH="${DATA_FOLDER:-./data}"
fi

echo "Using data directory: $DATA_PATH"

# Create parent directory if it doesn't exist
DATA_PARENT=$(dirname "$DATA_PATH")
if [ ! -d "$DATA_PARENT" ]; then
  echo "Creating parent directory: $DATA_PARENT"
  mkdir -p "$DATA_PARENT"
  chmod 755 "$DATA_PARENT"
fi

# Remove and recreate data directory with Docker-compatible permissions
echo "Setting up data directory: $DATA_PATH"

# Create data directory with Docker-compatible permissions
rm -rf "$DATA_PATH"
mkdir -p "$DATA_PATH"

# Set permissions for Docker Desktop on macOS
chmod 777 "$DATA_PATH"

# Create subdirectories with appropriate permissions
for dir in kafka flink timescale redpanda "shelly/logs"; do
  full_path="$DATA_PATH/$dir"
  mkdir -p "$full_path"
  chmod 777 "$full_path"
done

echo "Data directory structure created with Docker-compatible permissions"


# Remove existing containers and images before rebuilding
if [ -f ./base_services/$DOCKER_COMPOSE_FILE ]; then
  echo ""
  echo "************************************************"
  echo "* Removing existing Base Services containers   *"
  echo "************************************************"
  (cd ./base_services && docker compose -f $DOCKER_COMPOSE_FILE down --rmi all --remove-orphans)
fi

if [ -f ./integrations/shelly/$DOCKER_COMPOSE_FILE ]; then
  echo ""
  echo "************************************************"
  echo "* Removing existing Shelly integration containers *"
  echo "************************************************"
  (cd ./integrations/shelly && docker compose -f $DOCKER_COMPOSE_FILE down --rmi all --remove-orphans)
fi

# Build Base Services with --no-cache and --pull
if [ -f ./base_services/$DOCKER_COMPOSE_FILE ]; then
  echo ""
  echo "********************************************"
  echo "* Building Base Services (clean rebuild)   *"
  echo "********************************************"
  (cd ./base_services && docker compose -f $DOCKER_COMPOSE_FILE build --no-cache --pull --progress=plain)
  
  # Verify base services images were built
  echo ""
  echo "********************************************"
  echo "* Verifying Base Services images          *"
  echo "********************************************"
  (cd ./base_services && docker compose -f $DOCKER_COMPOSE_FILE images)
else
  echo "Warning: ./base_services/$DOCKER_COMPOSE_FILE not found."
fi

# Build Shelly Integration with --no-cache and --pull
if [ -f ./integrations/shelly/$DOCKER_COMPOSE_FILE ]; then
  echo ""
  echo "********************************************"
  echo "* Building Shelly integration (clean rebuild) *"
  echo "********************************************"
  (cd ./integrations/shelly && docker compose -f $DOCKER_COMPOSE_FILE build --no-cache --pull --progress=plain)
  
  # Verify Shelly images were built
  echo ""
  echo "********************************************"
  echo "* Verifying Shelly integration images     *"
  echo "********************************************"
  (cd ./integrations/shelly && docker compose -f $DOCKER_COMPOSE_FILE images)
else
  echo "Warning: ./integrations/shelly/$DOCKER_COMPOSE_FILE not found."
fi


# Ensure Flink job directories exist with correct permissions
FLINK_JOBS_DIR="$DATA_PATH/flink/jobs_jars"
sudo mkdir -p "$FLINK_JOBS_DIR" || true
sudo chown -R $(whoami):$(id -gn) "$DATA_PATH/flink"
sudo chmod -R 775 "$DATA_PATH/flink"
# Ensure the current user has write access to the jobs directory
chmod -R 775 "$FLINK_JOBS_DIR"

# Compile Flink jobs using the dedicated service
if [ -f ./base_services/$DOCKER_COMPOSE_FILE ]; then
  echo ""
  echo "***************************"
  echo "* Compiling Flink jobs *"
  echo "***************************"
  echo "Current directory: $(pwd)"
  echo "Flink jobs directory: $FLINK_JOBS_DIR"
  echo "Starting flink-job-compiler service..."
  
  # Export the DATA_FOLDER variable for the docker-compose environment
  export DATA_FOLDER="$DATA_PATH"
  
  (cd ./base_services && docker compose --no-ansi --profile compile -f $DOCKER_COMPOSE_FILE up --abort-on-container-exit flink-job-compiler)
  
  # Check if compilation was successful
  if [ $? -eq 0 ]; then
    echo -e "${GREEN}Flink job compilation completed successfully.${NC}"
  else
    echo -e "${RED}Error: Flink job compilation failed.${NC}"
    exit 1
  fi
else
  echo "Warning: ./base_services/$DOCKER_COMPOSE_FILE not found."
fi


# Start base containers, then shelly integration
if [ -f ./base_services/start_base_services.sh ]; then
  echo ""
  echo "**************************"
  echo "* Starting base services *"
  echo "**************************"
  (cd ./base_services && ./start_base_services.sh)
else
  echo "Warning: ./base_services/start_base_services.sh not found."
  echo "Current directory: $(pwd)"
  echo "Contents of base_services directory: $(ls -la ./base_services 2>/dev/null | grep start_base_services.sh || echo 'start_base_services.sh not found')"
fi


# Wait for base services to be healthy before starting Shelly integration
if [ -f ./integrations/shelly/start_shelly_integration.sh ]; then
  echo ""
  echo "***********************************"
  echo "* Starting Shelly integration     *"
  echo "***********************************"
  (cd ./integrations/shelly && ./start_shelly_integration.sh)
else
  echo "Warning: ./integrations/shelly/start_shelly_integration.sh not found."
  echo "Current directory: $(pwd)"
  echo "Contents of integrations/shelly directory: $(ls -la ./integrations/shelly 2>/dev/null | grep start_shelly_integration.sh || echo 'start_shelly_integration.sh not found')"
fi

# Optional cleanup of unused images
if [ "$FORCE" = false ]; then
  echo ""
  echo "***********************************"
  echo "* Optional: Clean up unused images *"
  echo "***********************************"
  echo "Do you want to clean up unused Docker images? This will remove all dangling images and unused containers. [y/N]"
  read -r CLEANUP
  if [[ "$CLEANUP" =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}Cleaning up unused images...${NC}"
    docker system prune -f
    echo -e "${GREEN}Cleanup complete.${NC}"
  else
    echo "Skipping image cleanup."
  fi
else
  echo "Skipping interactive image cleanup in force mode."
fi
