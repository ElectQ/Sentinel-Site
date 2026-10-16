"""Daily pipeline: scan configured sources → denoise new article URLs → bundles."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import llm
from . import state as state_mod
from .analyzers import bundle as bundle_mod
from .analyzers import feed as feed_mod
from .collectors import articles as articles_mod
from .collectors.sources import load_enabled
from .util import env_bool


def main() -> int:
    llm.reset_usage()
    sources = load_enabled()
    st = state_mod.load_sources()
    st["emitted"] = state_mod.load_emitted()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    bj = bundle_mod.beijing_date(now)

    print(f"sources_enabled={len(sources)} beijing_date={bj}")

    emitted: list[dict] = []
    failed: list[dict] = []
    recovered_sids: list[str] = []
    via_counts: dict[str, int] = {}
    baselines = 0

    for src in sources:
        prev_streak = st.get("sources", {}).get(src.id, {}).get("fail_streak", 0)
        result = articles_mod.collect_one(src, st, collected_at=now_iso)
        if not result["ok"]:
            failed.append({"id": src.id, "error": result.get("error")})
            print(f"FAIL {src.id}: {result.get('error')}")
            # Checkpoint failures too, so streaks survive a workflow timeout
            state_mod.save_sources(st)
            continue
        if prev_streak > 0:
            recovered_sids.append(src.id)
        via = result["via"] or "?"
        via_counts[via] = via_counts.get(via, 0) + 1
        if result["baseline"]:
            baselines += 1
            print(
                f"OK   {src.id}: via={via} baseline=1 seen={len(result['all_normalized'])} new=0"
            )
        else:
            new = result["new_articles"]
            candidate_text = ""
            if via != "rss":
                candidate_text = (
                    f" candidates={result.get('candidate_count', 0)}"
                    f" candidate_new={result.get('candidate_new_count', 0)}"
                )
            content_counts: dict[str, int] = {}
            for article in new:
                status = article.get("content_status") or "missing"
                content_counts[status] = content_counts.get(status, 0) + 1
            content_text = f" content={content_counts}" if content_counts else ""
            print(
                f"OK   {src.id}: via={via} new={len(new)}"
                f"{candidate_text}{content_text}"
            )
            for a in new:
                a["emitted"] = True
                emitted.append(a)

        # Checkpoint state incrementally so crashes never discard prior source progress
        state_mod.save_sources(st)
        state_mod.save_emitted(st["emitted"])

    # archive only emitted new articles (baseline updates state only)
    articles_mod.archive(emitted, when=now)

    # For feed/bundle: use this run's emitted items (also re-readable from archive)
    day_articles = list(emitted)
    # also merge any already archived today (same-day rerun)
    archived = articles_mod.collected_on(now.date().isoformat())
    # prefer archived that were emitted (have url)
    by_id = {a.get("external_id") or a.get("url"): a for a in archived}
    for a in emitted:
        by_id[a.get("external_id") or a.get("url")] = a
    day_articles = list(by_id.values())

    feed = feed_mod.build(day_articles, date=bj)
    feed_mod.write(feed)
    print(f"feed {feed['date']}: items={feed['item_count']}")

    bpath = bundle_mod.write_bundle_from_feed(
        feed,
        collect_date=bj,
        collected_at=now_iso,
        stats_extra={
            "sources_ok": len(sources) - len(failed),
            "sources_failed": failed,
            "baselines": baselines,
            "via_sources": via_counts,
            "failed_lists": [f["id"] for f in failed],
            "llm_usage": llm.usage_snapshot(),
        },
    )
    print(f"bundle: {bpath} items={feed['item_count']} failed={len(failed)}")
    print(f"llm_usage: {llm.usage_snapshot()}")

    for article in emitted:
        key = f"{article['source_id']}:{article['external_id']}"
        st["emitted"][key] = {
            "bundle_date": bj,
            "emitted_at": now_iso,
        }
    state_mod.save_sources(st)
    state_mod.save_emitted(st["emitted"])

    artifact_issues = check_artifacts(bpath)
    alerts = collect_alerts(sources, st, failed, emitted, artifact_issues)
    try:
        report_health(sources, st, failed, emitted, bj, bundle_path=bpath)
        sync_github_issues(
            failed,
            st.get("sources", {}),
            recovered_sids,
            alerts=alerts,
        )
    except Exception as exc:
        # Reporting/notification failures must not discard a successfully
        # collected bundle. The data commit step remains the delivery check.
        print(f"health_notification_error: {exc}")

    articles_mod.shutdown()

    # Source failures and notification/artifact warnings do not make the
    # collection step fail. A failed commit/push still fails the workflow.
    for issue in artifact_issues:
        print(f"ARTIFACT-WARNING {issue}")
    return 0


def _send_webhook(url: str, text: str) -> None:
    try:
        import httpx

        payload = {
            "msg_type": "text",
            "content": {"text": text},
            "text": text,
        }
        httpx.post(url, json=payload, timeout=10.0)
    except Exception as exc:
        print(f"webhook_send_error: {exc}")


def check_artifacts(bpath: str) -> list[str]:
    issues: list[str] = []
    bundle_path = Path(bpath)
    if not bundle_path.exists():
        issues.append(f"产物缺失: bundle 文件不存在 ({bpath})")
    else:
        try:
            bdata = json.loads(bundle_path.read_text(encoding="utf-8"))
            if not isinstance(bdata.get("items"), list):
                issues.append("产物格式异常: bundle items 字段非列表")
        except Exception as exc:
            issues.append(f"产物损坏: bundle json 解析失败 ({exc})")

    feed_file = Path("data/feed/latest.json")
    if not feed_file.exists():
        issues.append("产物缺失: data/feed/latest.json 不存在")
    else:
        try:
            json.loads(feed_file.read_text(encoding="utf-8"))
        except Exception as exc:
            issues.append(f"产物损坏: latest.json 解析失败 ({exc})")

    return issues


def collect_alerts(
    sources: list[Any],
    st: dict[str, Any],
    failed: list[dict[str, Any]],
    emitted: list[dict[str, Any]],
    artifact_issues: list[str] | None = None,
) -> list[dict[str, str]]:
    """Unified alert list consumed by both the health report and issue sync."""
    alerts: list[dict[str, str]] = []
    now_dt = datetime.now(timezone.utc)
    sources_dict = st.get("sources", {})

    for issue in artifact_issues or []:
        alerts.append({"id": "artifact", "category": "artifact", "detail": issue})

    for f in failed:
        sid = f["id"]
        err = str(f.get("error") or "")
        src = next((s for s in sources if s.id == sid), None)
        mode = getattr(src, "collect_mode", "unknown") if src else "unknown"
        streak = sources_dict.get(sid, {}).get("fail_streak", 1)

        advice = ""
        err_lower = err.lower()
        if "403" in err_lower or "cloudflare" in err_lower or "blocked" in err_lower:
            if mode != "browser_llm":
                advice = " [建议: 遭遇反爬/403，建议配置 browser_fallback 或升级为 browser_llm]"
            else:
                advice = " [建议: 浏览器模式仍遭阻断，可能需要更新反爬指纹或代理]"
        elif "timeout" in err_lower or "timed out" in err_lower:
            advice = " [建议: 网络超时，请检查目标服务器连通性]"

        blocked_markers = ("403", "cloudflare", "blocked", "challenge", "captcha", "验证码", "banned")
        category = "访问受限" if any(marker in err_lower for marker in blocked_markers) else "采集失败"
        alerts.append(
            {
                "id": sid,
                "category": category,
                "detail": f"连续 {streak} 次: {err[:120]}{advice}",
            }
        )

    for a in emitted:
        if a.get("content_status") == "failed" and "challenge_blocked" in str(
            a.get("content_error") or ""
        ):
            alerts.append(
                {
                    "id": str(a.get("source_id") or ""),
                    "category": "反爬拦截",
                    "detail": "详情页被验证码/阻断盾拦截，已放弃抓取避免脏数据",
                }
            )

    for src in sources:
        sst = sources_dict.get(src.id, {})
        mode = getattr(src, "collect_mode", "")
        method = str(sst.get("method") or "")

        # Layer 0 signal: an rss-declared source silently degrading to
        # browser/LLM collection (slower, costlier, candidate extraction
        # degraded). Only compare rss declarations; llm modes legitimately
        # resolve to several transports.
        if mode == "rss" and method and method != "rss":
            alerts.append(
                {
                    "id": src.id,
                    "category": "路径退化",
                    "detail": f"声明 rss，实际走 {method}，请检查 feed 地址",
                }
            )

        last_new = sst.get("last_new_at")
        if last_new:
            try:
                days = (now_dt - datetime.fromisoformat(last_new)).days
                if days >= 45 and sst.get("fail_streak", 0) == 0:
                    alerts.append(
                        {
                            "id": src.id,
                            "category": "长期静默",
                            "detail": f"连续 {days} 天无新内容，建议人工复查是否源已改版",
                        }
                    )
            except Exception:
                pass

    return alerts


def report_health(
    sources: list[Any],
    st: dict[str, Any],
    failed: list[dict[str, Any]],
    emitted: list[dict[str, Any]],
    date: str,
    bundle_path: str = "",
) -> str:
    lines = [
        f"### Sentinel 采集健康简报 ({date})",
        "",
        f"- 监控源总数: {len(sources)} | 成功: {len(sources) - len(failed)} | 失败: {len(failed)}",
        f"- 今日新发布文章: {len(emitted)} 篇",
        "",
    ]

    artifact_issues = check_artifacts(bundle_path) if bundle_path else []
    alerts = collect_alerts(sources, st, failed, emitted, artifact_issues)

    warnings: list[str] = []
    for alert in alerts:
        if alert["category"] == "artifact":
            warnings.append(f"- [产物异常] {alert['detail']}")
        else:
            warnings.append(f"- [{alert['category']}] {alert['id']}: {alert['detail']}")

    if warnings:
        lines.append("#### 异常与策略预警")
        lines.extend(warnings)
    else:
        lines.append("**所有数据源运行正常，无策略预警**")

    report_md = "\n".join(lines)
    print("\n" + report_md + "\n")

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        try:
            with open(summary_file, "a", encoding="utf-8") as sf:
                sf.write("\n" + report_md + "\n")
        except Exception:
            pass

    webhook_url = os.environ.get("REPORT_WEBHOOK_URL")
    if webhook_url:
        _send_webhook(webhook_url, report_md)

    return report_md


def sync_github_issues(
    failed: list[dict[str, Any]],
    sources_dict: dict[str, Any],
    recovered_sids: list[str],
    alerts: list[dict[str, str]] | None = None,
) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return

    import httpx

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    api_url = f"https://api.github.com/repos/{repo}/issues"

    issues: list[dict[str, Any]] = []
    page = 1
    try:
        while True:
            resp = httpx.get(
                api_url,
                params={
                    "state": "all",
                    "labels": "sentinel-alert",
                    "per_page": 100,
                    "page": page,
                },
                headers=headers,
                timeout=10.0,
            )
            if resp.status_code != 200:
                return
            batch = resp.json()
            issues.extend(batch)
            if len(batch) < 100:
                break
            page += 1
    except Exception:
        return

    # Keep one stable issue per source across both open and closed issues.
    # Reopen a closed issue on recurrence instead of creating a duplicate.
    issue_by_sid: dict[str, dict[str, Any]] = {}
    for issue in issues:
        title = issue.get("title") or ""
        if ": " not in title:
            continue
        sid = title.rsplit(": ", 1)[-1].strip()
        current = issue_by_sid.get(sid)
        if current is None or issue.get("state") == "open":
            issue_by_sid[sid] = issue

    streak_threshold = int(os.environ.get("ALERT_FAIL_STREAK", 3))
    issue_alerts: dict[str, dict[str, str]] = {}
    active_sids = {str(f.get("id")) for f in failed}

    for alert in alerts or []:
        sid = alert.get("id") or ""
        category = alert.get("category") or ""
        if not sid or sid == "artifact":
            continue
        if category not in {"采集失败", "访问受限", "路径退化", "反爬拦截"}:
            continue
        active_sids.add(sid)
        if category == "采集失败" and _parse_streak(alert.get("detail", "")) < streak_threshold:
            continue
        issue_alerts.setdefault(sid, alert)

    for sid, alert in issue_alerts.items():
        issue = issue_by_sid.get(sid)
        category = alert.get("category") or "健康异常"
        if issue:
            if issue.get("state") == "closed":
                issue_num = issue["number"]
                try:
                    httpx.patch(
                        f"{api_url}/{issue_num}",
                        json={"state": "open"},
                        headers=headers,
                        timeout=10.0,
                    )
                    httpx.post(
                        f"{api_url}/{issue_num}/comments",
                        json={"body": f"该源再次出现告警：{category}。\n\n{alert.get('detail', '')}"},
                        headers=headers,
                        timeout=10.0,
                    )
                except Exception:
                    pass
            continue

        body = (
            f"### 数据源健康告警\n\n"
            f"- **监控源**: `{sid}`\n"
            f"- **告警类别**: {category}\n"
            f"- **详情**: {alert.get('detail', '')}\n\n"
            "同一数据源复发时会重新打开此 Issue，不会重复创建。"
        )
        try:
            httpx.post(
                api_url,
                json={
                    "title": f"[alert] {category}: {sid}",
                    "body": body,
                    "labels": ["sentinel-alert"],
                },
                headers=headers,
                timeout=10.0,
            )
        except Exception:
            pass

    for sid, issue in issue_by_sid.items():
        if sid in active_sids or issue.get("state") != "open":
            continue
        issue_num = issue["number"]
        try:
            httpx.post(
                f"{api_url}/{issue_num}/comments",
                json={"body": "该源当前已恢复，自动关闭告警。"},
                headers=headers,
                timeout=10.0,
            )
            httpx.patch(
                f"{api_url}/{issue_num}",
                json={"state": "closed"},
                headers=headers,
                timeout=10.0,
            )
        except Exception:
            pass


def _parse_streak(detail: str) -> int:
    """Extract the streak number from a '连续 N 次' alert detail."""
    import re

    m = re.search(r"连续 (\d+) 次", detail)
    return int(m.group(1)) if m else 0


def run_standalone_health_check() -> int:
    sources = load_enabled()
    st = state_mod.load_sources()
    now = datetime.now(timezone.utc)
    bj = bundle_mod.beijing_date(now)
    latest_bundle = f"bundles/{bj}.json"
    if not Path(latest_bundle).exists():
        bundles = sorted(Path("bundles").glob("20*.json"))
        latest_bundle = str(bundles[-1]) if bundles else ""
    report_health(sources, st, [], [], bj, bundle_path=latest_bundle)
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        raise SystemExit(run_standalone_health_check())
    raise SystemExit(main())
