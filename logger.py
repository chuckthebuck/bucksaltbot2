"""Minimal line logger retained for legacy Pywikibot script compatibility."""

import os


class Logger:
    """Mirror script messages to stdout and an immediately flushed text file."""

    def __init__(self, log_file):
        """Open the environment-appropriate log path for a script run."""
        self.log_file = get_log_file(log_file)
        print(f"Logging to {self.log_file}")
        self.file_handler = open(self.log_file, "w+", encoding="utf-8")

    def log(self, message):
        """Write one message to both stdout and the backing file."""
        print(message)

        self.file_handler.write(message + "\n")
        self.file_handler.flush()

    def get_file_handler(self):
        """Return the underlying handle for compatibility callers."""
        return self.file_handler

    def close(self):
        """Close the backing log file."""
        self.file_handler.close()


def get_log_file(file_name):
    """Resolve a Toolforge data path in production or local logs otherwise."""
    if os.environ.get("NOTDEV"):
        return f"{os.environ.get('TOOL_DATA_DIR')}/logs/{file_name}.log"
    else:
        return f"./logs/{file_name}"
