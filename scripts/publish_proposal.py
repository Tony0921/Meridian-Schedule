"""在隔離 checkout 產生資料 commit；預設建立 PR，推送衝突時重新合併。"""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from collector.events import validate_event
from collector.github_dispatch import GitHubClient
from collector.http import ServiceError
from processor.classify import ConfidencePolicy
from processor.schemas import load_json, validate_schema
from processor.storage import read_data
from scripts.apply_proposal import apply_proposal
from scripts.process_post import ROOT


def git(*arguments, cwd, env):
    result = subprocess.run(["git", *arguments], cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode:
        raise ServiceError("Git 操作")
    return result.stdout.strip()


def publish(bundle, root, client, *, base="main", policy=None, attempts=3):
    policy = policy or ConfidencePolicy()
    event = validate_event({key: bundle["post"][key] for key in ("source", "post_id", "member_id")})
    validate_schema(bundle["proposal"], "changes")
    branch = "codex/post-" + hashlib.sha256((event["source"] + ":" + event["post_id"]).encode()).hexdigest()[:24]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    # 憑證透過環境傳給 git，避免出現在命令列、URL 或失敗日誌。
    credential = base64.b64encode(("x-access-token:" + client._token).encode()).decode()
    env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
               GIT_CONFIG_VALUE_0="AUTHORIZATION: basic " + credential)
    git("check-ref-format", "--branch", base, cwd=root, env=env)
    pending = client.pending_pr(branch)
    if pending:
        return {"result": "pending_review", "url": pending["html_url"]}
    remote = "https://github.com/" + client.repository + ".git"
    for attempt in range(attempts):
        git("fetch", "--no-tags", remote, base, cwd=root, env=env)
        with tempfile.TemporaryDirectory() as temp:
            checkout = Path(temp) / "checkout"
            git("worktree", "add", "--detach", str(checkout), "FETCH_HEAD", cwd=root, env=env)
            try:
                values = read_data(checkout / "data")
                if any((post["source"], post["post_id"]) == (event["source"], event["post_id"]) for post in values["posts"]):
                    return {"result": "duplicate"}
                applied = apply_proposal(bundle, checkout / "data", Path(temp) / "backups",
                                         approve=True, policy=policy, rebase=True)
                decision = applied["decision"]
                git("add", "--", "data/members.json", "data/schedule.json", "data/posts.json", "data/revisions.json", cwd=checkout, env=env)
                git("-c", "user.name=Meridian Schedule", "-c", "user.email=meridian-schedule@users.noreply.github.com",
                    "commit", "-m", "Update schedule from post " + event["post_id"], cwd=checkout, env=env)
                if decision == "review":
                    try:
                        git("push", remote, "HEAD:refs/heads/" + branch, cwd=checkout, env=env)
                    except ServiceError:
                        pending = client.pending_pr(branch)
                        if pending:
                            return {"result": "pending_review", "url": pending["html_url"]}
                        # 前次在 push 後中斷時，沿用已存在分支建立 PR，不 force-push。
                        existing = git("ls-remote", "--heads", remote, "refs/heads/" + branch, cwd=checkout, env=env)
                        if not existing:
                            raise
                    proposal = bundle["proposal"]
                    body = (f"來源：{bundle['post']['source_url']}\n\n"
                            f"分類：{proposal['classification']}；信心：{proposal['confidence']}。\n\n"
                            "此提案經 Schema、來源關聯與 deterministic merge 驗證。請檢查行程差異後合併。")
                    pr = client.create_pr(branch, base, "更新行程：" + event["member_id"] + " / " + event["post_id"], body)
                    return {"result": "pending_review", "url": pr["html_url"]}
                try:
                    git("push", remote, "HEAD:refs/heads/" + base, cwd=checkout, env=env)
                    return {"result": decision}
                except ServiceError:
                    if attempt == attempts - 1:
                        raise
                    # 另一篇貼文已更新 main；下次取最新資料並重跑 merge，不覆蓋整份舊快照。
            finally:
                git("worktree", "remove", str(checkout), cwd=root, env=env)
    raise ServiceError("推送重試耗盡")


def main(argv=None):
    parser = argparse.ArgumentParser(description="將提案發布為 PR，或依明確啟用的信心門檻提交")
    parser.add_argument("proposal", type=Path)
    parser.add_argument("--base", default=os.environ.get("SCHEDULE_BASE_BRANCH", "main"))
    args = parser.parse_args(argv)
    try:
        client = GitHubClient(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
        policy = ConfidencePolicy(float(os.environ.get("AUTO_MERGE_CONFIDENCE", "0.95")),
                                  float(os.environ.get("PR_CONFIDENCE", "0.70")),
                                  os.environ.get("REVIEW_ALL", "true").lower() != "false")
        print(json.dumps(publish(load_json(args.proposal), ROOT, client, base=args.base, policy=policy)))
        return 0
    except Exception as error:
        print(json.dumps({"result": "failed", "error": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
