"""API-map command — Map REST/GraphQL/gRPC routes to handlers."""

from apimap_engine import map_api_routes
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--method", choices=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                        default=None, help="Filter by HTTP method")
    parser.add_argument("--path", dest="path_filter", default=None,
                        help="Filter by route path substring")
    parser.add_argument("--production-only", dest="production_only", action="store_true",
                        default=False,
                        help="Filter out routes from test files (*.test.*, *.spec.*, __tests__/, test/, tests/)")


def execute(args, workspace):
    return map_api_routes(workspace, method=args.method, path_filter=args.path_filter)


register_command("api-map", "Map REST/GraphQL/gRPC routes to handlers", add_args, execute)
