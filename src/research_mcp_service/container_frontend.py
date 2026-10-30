"""Wait for this stack's private dependencies, then run the MCP frontend."""
from .wait_ready import main as wait_ready
from .server import main as serve

if __name__ == '__main__':
    wait_ready()
    serve()
