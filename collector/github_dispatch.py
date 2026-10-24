import re
from urllib.parse import urlencode

from collector.events import validate_event
from collector.http import JsonClient


class GitHubClient(JsonClient):
    def __init__(self, repository, token, *, timeout=30):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("repository 必須是 owner/name")
        super().__init__("https://api.github.com", token, timeout=timeout)
        self.repository = repository
        self.path = "/repos/" + repository

    def dispatch(self, event):
        self.request(self.path + "/dispatches", method="POST",
                     payload={"event_type": "new_x_post", "client_payload": validate_event(event)})

    def pending_pr(self, branch):
        owner = self.repository.split("/")[0]
        pulls = self.request(self.path + "/pulls?" + urlencode({"state": "open", "head": owner + ":" + branch}))
        return pulls[0] if pulls else None

    def create_pr(self, branch, base, title, body):
        return self.request(self.path + "/pulls", method="POST",
                            payload={"head": branch, "base": base, "title": title, "body": body})
