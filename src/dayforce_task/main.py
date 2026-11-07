"""Entry point. Run with: python -m dayforce_task.main"""

from dayforce_task import __version__
from dayforce_task.config import DATA_DIR


def main() -> None:
    print(f"dayforce_task {__version__}")
    print(f"Data folder: {DATA_DIR}")


if __name__ == "__main__":
    main()
