"""Only test fixtures; production has no in-memory/plaintext credential fallback."""
class MemoryCredentials:
    def __init__(self):
        self.value = None
    def load(self):
        return self.value
    def save(self, value):
        self.value = value
    def delete(self):
        self.value = None
