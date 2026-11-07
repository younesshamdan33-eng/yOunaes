class CieError(Exception):
    def __init__(self, message, status=400, reasons=None):
        super().__init__(message)
        self.status, self.reasons = status, reasons or []
