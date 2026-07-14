"""Allow ``python -m stateleak`` as an alias for the ``stateleak`` script."""

from .cli import console_main

if __name__ == "__main__":
    console_main()
