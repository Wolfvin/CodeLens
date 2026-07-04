"""Dashboard command — Generate HTML visualization dashboard."""

import os
import webbrowser
from commands import register_command
from dashboard_engine import generate_dashboard


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--output", "-o", default=None,
                        help="Output HTML file path (default: .codelens/dashboard.html)")
    parser.add_argument("--open", action="store_true",
                        help="Open dashboard in browser after generation")
    parser.add_argument("--watch", action="store_true",
                        help="Auto-regenerate dashboard on file changes")
    parser.add_argument("--compare", nargs=2, metavar=("SNAPSHOT1", "SNAPSHOT2"),
                        help="Compare two history snapshots (filenames from .codelens/history/)")


def execute(args, workspace):
    output_path = getattr(args, 'output', None)
    should_open = getattr(args, 'open', False)
    should_watch = getattr(args, 'watch', False)
    compare = getattr(args, 'compare', None)

    # Convert compare tuple
    compare_snapshots = None
    if compare:
        compare_snapshots = (compare[0], compare[1])

    result = generate_dashboard(
        workspace,
        output_path=output_path,
        compare_snapshots=compare_snapshots,
    )

    # Open in browser if requested
    if should_open and result.get("status") == "ok":
        dashboard_path = result.get("dashboard_path", "")
        if dashboard_path and os.path.exists(dashboard_path):
            try:
                webbrowser.open(f"file://{dashboard_path}")
            except Exception:
                pass

    # Watch mode
    if should_watch and result.get("status") == "ok":
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class DashboardRegenHandler(FileSystemEventHandler):
                def __init__(self, ws, out):
                    self.workspace = ws
                    self.output = out

                def on_modified(self, event):
                    if not event.is_directory and not event.src_path.endswith('.json'):
                        # Don't trigger on our own output
                        if '.codelens' not in event.src_path:
                            print(f"[CodeLens] File changed: {event.src_path}, regenerating dashboard...")
                            try:
                                generate_dashboard(self.workspace, output_path=self.output)
                            except Exception as e:
                                print(f"[CodeLens] Error regenerating: {e}")

            observer = Observer()
            handler = DashboardRegenHandler(workspace, output_path)
            observer.schedule(handler, workspace, recursive=True)
            observer.start()
            print(f"[CodeLens] Dashboard watch mode started. Press Ctrl+C to stop.")
            try:
                while True:
                    import time
                    time.sleep(1)
            except KeyboardInterrupt:
                observer.stop()
            observer.join()
        except ImportError:
            result["watch_warning"] = "watchdog not installed. Install with: pip install watchdog"
        except Exception as e:
            result["watch_warning"] = f"Watch mode failed: {e}"

    return result


register_command("dashboard", "Generate HTML visualization dashboard", add_args, execute,

hidden=True,

deprecated_alias_for='summary',

)
