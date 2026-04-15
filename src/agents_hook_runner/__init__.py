import sys

from .cli import WorkflowError, main as cli_main


def main() -> int:
    try:
        return cli_main()
    except WorkflowError as error:
        print(str(error), file=sys.stderr)
        return 1


__all__ = ["main"]
