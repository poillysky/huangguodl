#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hg_dl.py — 黄果剧集下载器 CLI

核心逻辑在 packages/core/hg_core；本文件保留命令行入口，并再导出公共 API，
使 test_hg_dl / web.py 的 `import hg_dl` 继续可用。
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import os
import sys

# ---------------------------------------------------------------------------
# 让 packages/core 可被 import（CLI / 测试 / 本机直接 python hg_dl.py）
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_CORE_PATH = os.path.join(_HERE, "packages", "core")
if _CORE_PATH not in sys.path:
    sys.path.insert(0, _CORE_PATH)

from hg_core import (  # noqa: E402
    CACHE_FILE,
    CATEGORIES,
    DEFAULT_API,
    DEFAULT_COVER_PROXY,
    DEFAULT_COVER_TOKEN,
    DEFAULT_HEADERS,
    VIDEO_EXT,
    Cache,
    HGApi,
    Job,
    Show,
    already_done,
    build_cover_url,
    build_jobs,
    clean_title,
    cover_path,
    download,
    download_cover,
    download_hls_ffmpeg,
    ensure_emby_metadata,
    resolve_ffmpeg,
    extract_episode,
    fmt_eps,
    human_size,
    local_has,
    log,
    normalize,
    parse_ep_filter,
    print_episodes,
    print_shows,
    resolve_show,
    save_cover,
    scan_local,
    show_dir,
    show_from_dict,
    target_path,
    title_score,
)

# 再导出：外部仍可 from hg_dl import ...
__all__ = [
    "CACHE_FILE", "CATEGORIES", "DEFAULT_API", "DEFAULT_COVER_PROXY",
    "DEFAULT_COVER_TOKEN", "DEFAULT_HEADERS", "VIDEO_EXT",
    "Cache", "HGApi", "Job", "Show",
    "already_done", "build_cover_url", "build_jobs", "clean_title",
    "cover_path", "download", "download_cover", "download_hls_ffmpeg",
    "ensure_emby_metadata", "extract_episode", "fmt_eps", "human_size",
    "local_has", "log", "normalize", "parse_ep_filter", "print_episodes",
    "print_shows", "resolve_ffmpeg", "resolve_show", "save_cover", "scan_local",
    "show_dir", "show_from_dict", "target_path", "title_score",
]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def add_common(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--api", default=DEFAULT_API, help=f"API 地址（默认 {DEFAULT_API}）")
    ap.add_argument("--out", default=".", help="下载输出目录（默认 当前目录）")
    ap.add_argument("--timeout", type=int, default=20, help="接口超时秒数")
    ap.add_argument("--refresh", action="store_true", help="忽略本地缓存，重新拉目录")
    ap.add_argument("--no-proxy", action="store_true", help="不启用 .part 续传标记")
    ap.add_argument("--cover-proxy", default=DEFAULT_COVER_PROXY,
                    help="封面解密代理地址，留空则直接取原图")
    ap.add_argument("--cover-token", default=DEFAULT_COVER_TOKEN, help="封面代理 Token")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="黄果剧集下载器：目录从网络拉，本地只管下载",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="拉取远端剧集目录")
    p_list.add_argument("--category", default="hot",
                        help="分类：" + " / ".join(f"{k}({v})" for k, v in CATEGORIES.items()))
    p_list.add_argument("--page", type=int, default=1, help="页码")
    p_list.add_argument("--page-size", type=int, default=24, help="每页条数")
    p_list.add_argument("--keyword", default="", help="改为按关键词搜索")
    add_common(p_list)

    p_show = sub.add_parser("show", help="看某部剧的集数列表")
    p_show.add_argument("title", help="剧名")
    p_show.add_argument("--threshold", type=float, default=0.62, help="匹配阈值")
    add_common(p_show)

    p_get = sub.add_parser("get", help="下载某部剧")
    p_get.add_argument("title", help="剧名")
    p_get.add_argument("--ep", default="", help="指定集，如 1,3,5 或 1-10")
    p_get.add_argument("--scan-dir", default="", help="扫描此本地目录，比对已有集数")
    # 去重是默认行为（scan-dir / 输出目录已有集一律跳过）；保留此参数仅为兼容旧命令。
    p_get.add_argument("--missing-only", action="store_true",
                       help="（已默认生效，保留兼容）只下本地没有的集")
    p_get.add_argument("--yes", action="store_true", help="跳过确认，直接下载")
    p_get.add_argument("--workers", type=int, default=3, help="并发数（默认 3）")
    p_get.add_argument("--retries", type=int, default=3, help="失败重试次数")
    p_get.add_argument("--dl-timeout", type=int, default=60, help="下载超时秒数")
    p_get.add_argument("--threshold", type=float, default=0.62, help="匹配阈值")
    p_get.add_argument("--cover", action="store_true", help="同时下载封面（默认开，--no-cover 关）")
    p_get.add_argument("--no-cover", dest="cover", action="store_false", help="不下载封面")
    p_get.set_defaults(cover=True)
    add_common(p_get)

    p_cover = sub.add_parser("cover", help="只下载封面")
    p_cover.add_argument("title", nargs="?", default="", help="剧名，留空则下载目录页全部")
    p_cover.add_argument("--category", default="hot", help="配合留空剧名时使用")
    p_cover.add_argument("--page", type=int, default=1)
    p_cover.add_argument("--limit", type=int, default=0, help="最多下几部，0=不限")
    p_cover.add_argument("--workers", type=int, default=4, help="并发数")
    p_cover.add_argument("--yes", action="store_true", help="跳过确认")
    p_cover.add_argument("--threshold", type=float, default=0.62)
    add_common(p_cover)

    p_int = sub.add_parser("interactive", help="交互式浏览并下载")
    p_int.add_argument("--workers", type=int, default=3)
    p_int.add_argument("--retries", type=int, default=3)
    p_int.add_argument("--dl-timeout", type=int, default=60)
    p_int.add_argument("--yes", action="store_true", help="跳过确认")
    add_common(p_int)

    return ap


def make_api(args: argparse.Namespace) -> HGApi:
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    cache = Cache(os.path.join(out_dir, CACHE_FILE))
    return HGApi(args.api, cache=cache, cache_ttl=0 if args.refresh else 1800)


def cmd_list(args: argparse.Namespace) -> int:
    api = make_api(args)
    if args.keyword:
        shows = api.search(args.keyword, args.page)
        log(f"搜索「{args.keyword}」第 {args.page} 页 — {len(shows)} 条")
    else:
        shows = api.catalog(args.category, args.page, args.page_size)
        name = CATEGORIES.get(args.category, args.category)
        log(f"分类 {name}（{args.category}）第 {args.page} 页 — {len(shows)} 条")
    print_shows(shows)
    if api.cache:
        api.cache.save()
    return 0


def cmd_cover(args: argparse.Namespace) -> int:
    api = make_api(args)
    out_dir = os.path.abspath(args.out)

    if args.title.strip():
        show = resolve_show(api, args.title, args.threshold)
        shows = [show] if show else []
    else:
        shows = api.catalog(args.category, args.page)
        log(f"分类 {CATEGORIES.get(args.category, args.category)} 第 {args.page} 页 — {len(shows)} 部")
    if args.limit > 0:
        shows = shows[: args.limit]
    if not shows:
        return 1

    log("")
    log(f"将下载 {len(shows)} 部剧的封面到 {out_dir}")
    if not args.yes:
        log("（预览模式，加 --yes 执行）")

    if not args.yes and sys.stdin and sys.stdin.isatty():
        try:
            if input("确认？输入 y 继续: ").strip().lower() not in ("y", "yes"):
                log("已取消", level="warn")
                return 0
        except (EOFError, KeyboardInterrupt):
            log("已取消", level="warn")
            return 0

    ok = fail = 0
    results: list[tuple[Show, bool, str]] = []
    with futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(download_cover, s, api, out_dir, args): s for s in shows}
        for fut in futures.as_completed(futs):
            s = futs[fut]
            good, note = fut.result()
            results.append((s, good, note))
    for s, good, note in sorted(results, key=lambda x: x[0].title):
        if good:
            ok += 1
            log(f"  ✓ {s.title} · {note}")
        else:
            fail += 1
            log(f"  ✗ {s.title} · {note}", level="err")
    if api.cache:
        api.cache.save()
    log("")
    log(f"完成：成功 {ok}，失败 {fail}")
    return 0 if fail == 0 else 2


def cmd_show(args: argparse.Namespace) -> int:
    api = make_api(args)
    show = resolve_show(api, args.title, args.threshold)
    if not show:
        return 1
    eps = api.episodes(show)
    log(f"\n《{show.title}》共 {len(eps)} 集")
    print_episodes(eps, title=show.title)
    if api.cache:
        api.cache.save()
    return 0


def run_jobs(jobs: list[Job], api: HGApi, args: argparse.Namespace, out_dir: str) -> int:
    if not args.yes:
        log("")
        log(f"即将下载 {len(jobs)} 集到 {out_dir}")
        if not sys.stdin or not sys.stdin.isatty():
            log("非交互终端无法确认，已取消。批量下载请加 --yes。", level="warn")
            return 1
        try:
            ans = input("确认下载？输入 y 继续: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            log("已取消", level="warn")
            return 1
        if ans not in ("y", "yes"):
            log("已取消", level="warn")
            return 1

    log("")
    ok = fail = 0
    with futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(download, j, api, out_dir,
                            timeout=args.dl_timeout, retries=args.retries): j for j in jobs}
        for fut in futures.as_completed(futs):
            j = fut.result()
            if j.status == "ok":
                ok += 1
                log(f"  ✓ 第{j.ep}集 · {j.note}")
            elif j.status == "exist":
                log(f"  · 第{j.ep}集 · 已存在")
            else:
                fail += 1
                log(f"  ✗ 第{j.ep}集 · {j.note}", level="err")
    if api.cache:
        api.cache.save()
    log("")
    log(f"完成：成功 {ok}，失败 {fail}")
    return 0 if fail == 0 else 2


def do_cover(show: Show, api: HGApi, out_dir: str, args: argparse.Namespace) -> None:
    good, note = download_cover(show, api, out_dir, args)
    if good:
        log(f"  ✓ 封面 · {note}")
    else:
        log(f"  ✗ 封面 · {note}", level="warn")


def cmd_get(args: argparse.Namespace) -> int:
    api = make_api(args)
    out_dir = os.path.abspath(args.out)
    show = resolve_show(api, args.title, args.threshold)
    if not show:
        return 1

    eps = api.episodes(show)
    if not eps:
        log("没拿到集数列表，无法继续。", level="err")
        if api.cache:
            api.cache.save()
        return 1

    local_map = scan_local(args.scan_dir) if args.scan_dir else {}
    if args.scan_dir:
        log(f"本地目录 {args.scan_dir}：识别到 {len(local_map)} 部剧")
    ep_filter = parse_ep_filter(args.ep)

    jobs, have = build_jobs(show, eps, ep_filter=ep_filter, local_map=local_map,
                            out_dir=out_dir)
    total = len(eps)
    log("")
    log(f"《{show.title}》远端共 {total} 集")
    log(f"  本地已有: {fmt_eps(have) if have else '无'}")
    if ep_filter:
        log(f"  集数过滤: {fmt_eps(sorted(ep_filter))}")
    log(f"  待下载  : {fmt_eps([j.ep for j in jobs]) if jobs else '无'}")
    if api.cache:
        api.cache.save()

    if not jobs:
        if args.cover:
            do_cover(show, api, out_dir, args)
        log("\n没有需要下载的集。")
        return 0
    if not args.yes:
        log("")
        log(f"以上是计划，未下载任何文件（共 {len(jobs)} 集"
            f"{'，含封面' if args.cover else ''}）。确认无误后加 --yes 执行。")
        return 0

    if args.cover:
        do_cover(show, api, out_dir, args)
    return run_jobs(jobs, api, args, out_dir)


def cmd_interactive(args: argparse.Namespace) -> int:
    api = make_api(args)
    out_dir = os.path.abspath(args.out)
    page = 1
    category = "hot"

    while True:
        try:
            if category.startswith("/"):
                shows = api.search(category[1:], page)
            else:
                shows = api.catalog(category, page)
        except RuntimeError as exc:
            log(f"拉目录失败: {exc}", level="err")
            return 1

        name = CATEGORIES.get(category, category.lstrip("/"))
        log("")
        log(f"═══ {name} · 第 {page} 页 ═══")
        print_shows(shows)

        try:
            cmd = input(
                "\n输入序号下该剧 | n 下一页 | p 上一页 | /关键词 搜索 | @分类 切换 | q 退出\n> "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            log("\n退出", level="warn")
            return 0

        if not cmd or cmd == "q":
            return 0
        if cmd == "n":
            page += 1
            continue
        if cmd == "p":
            page = max(1, page - 1)
            continue
        if cmd.startswith("/"):
            category, page = cmd, 1
            continue
        if cmd.startswith("@"):
            key = cmd[1:].strip() or "hot"
            category = key if key in CATEGORIES else "hot"
            page = 1
            log("可用分类: " + ", ".join(CATEGORIES))
            continue
        if cmd.isdigit():
            idx = int(cmd)
            if not (1 <= idx <= len(shows)):
                log("序号超出范围", level="warn")
                continue
            show = shows[idx - 1]
            eps = api.episodes(show)
            log("")
            log(f"《{show.title}》共 {len(eps)} 集")
            print_episodes(eps)
            try:
                sub = input("要下哪些集？如 1 / 1-10 / all（回车=跳过）> ").strip()
            except (EOFError, KeyboardInterrupt):
                return 0
            if not sub:
                continue
            ep_filter = None if sub.lower() == "all" else parse_ep_filter(sub)
            jobs, _have = build_jobs(show, eps, ep_filter=ep_filter, local_map={},
                                     out_dir=out_dir)
            if not jobs:
                if getattr(args, "cover", False):
                    do_cover(show, api, out_dir, args)
                log("无待下载", level="warn")
                continue
            args.yes = getattr(args, "yes", False)
            if getattr(args, "cover", False):
                do_cover(show, api, out_dir, args)
            run_jobs(jobs, api, args, out_dir)
            if api.cache:
                api.cache.save()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "list":
            return cmd_list(args)
        if args.cmd == "show":
            return cmd_show(args)
        if args.cmd == "get":
            return cmd_get(args)
        if args.cmd == "cover":
            return cmd_cover(args)
        if args.cmd == "interactive":
            return cmd_interactive(args)
    except KeyboardInterrupt:
        log("\n已中断（.part 保留，重跑续传）", level="warn")
        return 130
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
