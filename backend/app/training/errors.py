class PreflightError(ValueError):
    def __init__(self, issues: list[dict]):
        super().__init__("；".join(issue["message"] for issue in issues))
        self.issues = issues
