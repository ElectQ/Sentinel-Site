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

    report_health(sources, st, failed, emitted, bj, bundle_path=bpath)
    sync_github_issues(failed, st.get("sources", {}), recovered_sids)

    articles_mod.shutdown()

    if env_bool("STRICT", False) and failed:
        return 1
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

    warnings: list[str] = []
    sources_dict = st.get("sources", {})

    if bundle_path:
        for issue in check_artifacts(bundle_path):
            warnings.append(f"- [产物异常] {issue}")

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

        warnings.append(
            f"- [采集失败] {sid} (连续 {streak} 次): {err[:80]}{advice}"
        )

    for a in emitted:
        if a.get("content_status") == "failed" and "challenge_blocked" in str(
            a.get("content_error") or ""
        ):
            warnings.append(
                f"- [反爬拦截] {a.get('source_id')}: 详情页被验证码/阻断盾拦截，已放弃抓取避免脏数据"
            )

    now_dt = datetime.now(timezone.utc)
    for src in sources:
        sst = sources_dict.get(src.id, {})
        last_new = sst.get("last_new_at")
        if last_new:
            try:
                days = (now_dt - datetime.fromisoformat(last_new)).days
                if days >= 45 and sst.get("fail_streak", 0) == 0:
                    warnings.append(
                        f"- [长期静默] {src.id}: 连续 {days} 天无新内容，建议人工复查是否源已改版"
                    )
            except Exception:
                pass

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

    try:
        resp = httpx.get(
            api_url,
            params={"state": "open", "labels": "sentinel-alert"},
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code != 200:
            return
        open_issues = resp.json()
    except Exception:
        return

    open_by_sid: dict[str, dict[str, Any]] = {}
    for issue in open_issues:
        title = issue.get("title") or ""
        if ": " in title:
            sid = title.split(": ")[-1].strip()
            open_by_sid[sid] = issue

    streak_threshold = int(os.environ.get("ALERT_FAIL_STREAK", 3))

    for f in failed:
        sid = f["id"]
        streak = sources_dict.get(sid, {}).get("fail_streak", 1)
        if streak >= streak_threshold and sid not in open_by_sid:
            err = str(f.get("error") or "")
            body = (
                f"### 数据源采集连续失败告警\n\n"
                f"- **监控源**: `{sid}`\n"
                f"- **连续失败次数**: {streak} 次\n"
                f"- **最新错误**: `{err[:300]}`\n\n"
                f"系统自检建议: 请检查该源是否已更换域名、反爬规则升级或 Feed 地址失效。"
            )
            try:
                httpx.post(
                    api_url,
                    json={
                        "title": f"[alert] 采集失败: {sid}",
                        "body": body,
                        "labels": ["sentinel-alert"],
                    },
                    headers=headers,
                    timeout=10.0,
                )
            except Exception:
                pass

    for sid in recovered_sids:
        if sid in open_by_sid:
            issue_num = open_by_sid[sid]["number"]
            try:
                httpx.post(
                    f"{api_url}/{issue_num}/comments",
                    json={"body": "该监控源已恢复正常采集，连续失败状态已重置。系统自动关闭此 Issue。"},
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
