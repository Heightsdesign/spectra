"""Keep staff search terms out of the application's Uvicorn access log."""
import logging


class IntakeAccessPrivacy(logging.Filter):
    def filter(self, record):
        # Uvicorn's request-line tuple: client, method, path-with-query, HTTP version, status.
        if isinstance(record.args, tuple) and len(record.args) == 5:
            values = list(record.args)
            if isinstance(values[2], str) and values[2].split('?', 1)[0].startswith('/internal/intake/'):
                values[2] = values[2].split('?', 1)[0]
                record.args = tuple(values)
        return True
