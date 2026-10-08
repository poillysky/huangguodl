#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cli_smoke.py — 用真实命令行入口跑一遍完整流程。

在同一个进程里起 mock API，再用子进程调 hg_dl.py 的 argparse 入口，
验证 list / show / get（含 --yes 真实下载）三条命令都能跑通。
不打真实网络，不下载任何真实内容。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import mock_api                                    # noqa: E402

PY = sys.executable
FAILS: list[str] = []


def run(args: list[str], cwd: str) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(
        [PY, os.path.join(ROOT, "hg_dl.py"), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def media_files(root: str, ext: str) -> list[str]:
    found: list[str] = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.endswith(ext):
                found.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return sorted(found)


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}")
    if not cond:
        if detail:
            print("       " + detail.replace("\n", "\n       ")[:1200])
        FAILS.append(name)


def main() -> int:
    srv = mock_api.serve(0)
    base = f"http://127.0.0.1:{srv.server_port}"
    tmp = tempfile.mkdtemp(prefix="hgcli_")
    print(f"mock api: {base}\nworkdir  : {tmp}\n")

    try:
        # 1) list
        rc, out = run(["list", "--api", base], tmp)
        check("list 返回 0", rc == 0, out)
        check("list 输出含都市逆袭传", "都市逆袭传" in out, out)
        check("list 输出含序号", "[  1]" in out, out)

        # 2) list --category / --keyword
        rc, out = run(["list", "--category", "new", "--api", base], tmp)
        check("list --category new", rc == 0 and "最新" in out, out)

        rc, out = run(["list", "--keyword", "都市", "--api", base], tmp)
        check("list --keyword", rc == 0 and "搜索" in out, out)

        # 3) show
        rc, out = run(["show", "都市逆袭传", "--api", base], tmp)
        check("show 返回 0", rc == 0, out)
        check("show 列出 8 集", out.count("第") >= 8 and "共 8 集" in out, out)
        check("show 显示集标题", "第1集 初入都市" in out, out)

        # 4) get（dry-run，不加 --yes 应该只打印计划，不下载也不弹确认）
        rc, out = run(["get", "都市逆袭传", "--ep", "1,2,3", "--api", base], tmp)
        check("get dry-run 返回 0", rc == 0, out)
        check("get dry-run 声明未下载", "未下载任何文件" in out, out)
        check("get dry-run 不弹确认框", "确认下载？" not in out, out)
        check("get dry-run 未产生文件",
              not media_files(tmp, ".mp4"),
              str(os.listdir(tmp)))

        # 5) get --yes 真下载
        rc, out = run(["get", "都市逆袭传", "--ep", "1,2,3", "--yes",
                       "--workers", "3", "--api", base], tmp)
        check("get --yes 返回 0", rc == 0, out)
        check("get 下载 3 集成功", "成功 3" in out, out)
        mp4s = media_files(tmp, ".mp4")
        check("磁盘产生 3 个 mp4", len(mp4s) == 3, str(mp4s))
        # 内容必须是 mock 的确定性字节，且与源数据一致
        sizes = {os.path.getsize(os.path.join(tmp, f)) for f in mp4s}
        check("文件大小一致(512KB)", sizes == {512 * 1024}, str(sizes))
        check("文件名含剧名与集号",
              all("都市逆袭传" in f for f in mp4s)
              and all("Season 01" in f.replace("\\", "/") for f in mp4s)
              and "S01E03" in "".join(mp4s),
              str(mp4s))

        # 6) 重复 get 应全部跳过
        rc, out = run(["get", "都市逆袭传", "--ep", "1,2,3", "--yes", "--api", base], tmp)
        check("重复下载无待下载项", "没有需要下载" in out, out)

        # 7) --scan-dir + --missing-only 补缺集
        scan_dir = os.path.join(tmp, "已有剧集")
        os.makedirs(scan_dir, exist_ok=True)
        for ep in (1, 2, 3):
            with open(os.path.join(scan_dir, f"都市逆袭传 - 第{ep}集.mp4"), "wb") as fh:
                fh.write(b"local")
        rc, out = run(["get", "都市逆袭传", "--scan-dir", scan_dir, "--missing-only",
                       "--yes", "--api", base], tmp)
        check("missing-only 只下 4-8 集",
              "成功 5" in out and "第4集" in out and "第8集" in out, out)
        new = [
            f for f in media_files(tmp, ".mp4")
            if f not in mp4s and "已有剧集" not in f.replace("/", "\\")
        ]
        check("新增 5 个文件", len(new) == 5, str(new))
        check("缺集报告正确",
              "本地已有: 1-3" in out, out)

        # 8) --ep 区间
        rc, out = run(["get", "豪门夜色", "--ep", "1-2", "--yes", "--api", base], tmp)
        check("区间选集可用", "成功 2" in out, out)

        # 8b) 默认带封面下载
        rc, out = run(["get", "都市修仙传", "--ep", "1", "--yes",
                       "--cover-proxy", f"{base}/proxy",
                       "--cover-token", mock_api.EXPECT_TOKEN,
                       "--api", base], tmp)
        check("get 默认带封面", "封面" in out and "✓ 封面" in out, out)
        jpg = [f for f in media_files(tmp, ".jpg") if "都市修仙传" in f]
        check("磁盘产生封面",
              any(f.replace("\\", "/").endswith("都市修仙传/poster.jpg") for f in jpg),
              str(jpg))
        if jpg:
            root_poster = next(
                (f for f in jpg if f.replace("\\", "/").endswith("/poster.jpg")),
                jpg[0],
            )
            with open(os.path.join(tmp, root_poster), "rb") as fh:
                head = fh.read(4)
            check("封面是有效 JPEG", head == b"\xff\xd8\xff\xe0", repr(head))
        nfos = [f for f in media_files(tmp, ".nfo") if "都市修仙传" in f]
        check("产生 tvshow.nfo",
              any(f.replace("\\", "/").endswith("都市修仙传/tvshow.nfo") for f in nfos),
              str(nfos))

        # 8c) --no-cover 应跳过封面
        rc, out = run(["get", "深夜食堂都市篇", "--ep", "1", "--yes", "--no-cover",
                       "--api", base], tmp)
        check("--no-cover 不下封面", "封面" not in out.split("待下载")[-1], out)

        # 8d) 封面 token 错时应报出原因，且不写出坏图
        n_jpg_before = len(media_files(tmp, ".jpg"))
        rc, out = run(["get", "旧剧重播2024", "--ep", "1", "--yes",
                       "--cover-proxy", f"{base}/proxy", "--cover-token", "BAD",
                       "--api", base], tmp)
        check("封面失败不阻断正片", "成功 1" in out, out)
        check("封面错误原因透出", "403" in out and "invalid token" in out, out)
        n_jpg_after = len(media_files(tmp, ".jpg"))
        check("错误响应未写成 jpg", n_jpg_after == n_jpg_before,
              f"{n_jpg_before} -> {n_jpg_after}")

        # 9) cover 子命令
        rc, out = run(["cover", "都市逆袭传", "--yes",
                       "--cover-proxy", f"{base}/proxy",
                       "--cover-token", mock_api.EXPECT_TOKEN,
                       "--api", base], tmp)
        check("cover 子命令可用", rc == 0 and "成功 1" in out, out)

        rc, out = run(["cover", "--yes", "--limit", "2",
                       "--cover-proxy", f"{base}/proxy",
                       "--cover-token", mock_api.EXPECT_TOKEN,
                       "--api", base], tmp)
        check("cover 批量下载", "成功 2" in out, out)

        # 10) 匹配失败应拒绝而非乱下
        rc, out = run(["get", "不存在的剧名xyz", "--api", base], tmp)
        check("匹配失败返回非 0", rc != 0, out)
        check("匹配失败给出候选", "最接近" in out or "无候选" in out, out)

        # 10) --help 可用
        rc, out = run(["--help"], tmp)
        check("--help 可用", rc == 0 and "剧集下载器" in out, out)

        rc, out = run(["get", "--help"], tmp)
        check("get --help 可用", rc == 0 and "--missing-only" in out, out)

    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项: " + ", ".join(FAILS))
        return 1
    print("CLI 冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())