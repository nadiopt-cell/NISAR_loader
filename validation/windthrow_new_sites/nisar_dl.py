# -*- coding: utf-8 -*-
"""Resume-загрузчик GUNW-гранул: докачивает parts за несколько запусков.

Каждый запуск работает не дольше BUDGET сек (по умолчанию 460),
потом чисто выходит; повторный запуск продолжает с места остановки.
Когда оба файла собраны и проверены — exit 0 и печать "COMPLETE".

Запуск: nisar_dl.py <site>
"""
import os
import sys
import time
from pathlib import Path

import requests

# WP-3: the EDL token comes from the environment, never a file path
TOKEN = os.environ.get("EDL_TOKEN", "").strip()
if not TOKEN:
    sys.exit("EDL_TOKEN environment variable is not set")
OUT = Path("/home/z/my-project/upload/nisar_new")
B = "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GUNW_PROVISIONAL_V1"
BUDGET = int(os.environ.get("BUDGET", "460"))
NCHUNK = 6
HDR = {"Authorization": "Bearer " + TOKEN}

PAIRS = {
    "nnov_sukhona": [
        "NISAR_L2_PR_GUNW_024_099_A_030_025_2000_SH_20260703T012709_20260703T012745_20260715T012709_20260715T012744_P05023_N_F_J_001",
        "NISAR_L2_PR_GUNW_025_099_A_030_026_2000_SH_20260715T012709_20260715T012744_20260727T012708_20260727T012743_P05023_N_F_J_001",
    ],
    "kostroma_108": [
        "NISAR_L2_PR_GUNW_024_108_D_059_025_2000_SH_20260703T164247_20260703T164323_20260715T164246_20260715T164322_P05023_N_F_J_001",
        "NISAR_L2_PR_GUNW_025_108_D_059_026_2000_SH_20260715T164246_20260715T164322_20260727T164245_20260727T164321_P05023_N_F_J_001",
    ],
    "kirov_slav": [
        "NISAR_L2_PR_GUNW_026_041_A_032_028_2000_SH_20260723T005500_20260723T005536_20260816T005458_20260816T005534_P05023_N_F_J_001",
        "NISAR_L2_PR_GUNW_028_041_A_032_030_2000_SH_20260816T005458_20260816T005534_20260909T005458_20260909T005534_P05023_N_F_J_001",
    ],
    "chelyabinsk": [
        "NISAR_L2_PR_GUNW_023_084_A_030_025_2000_SH_20260620T002854_20260620T002912_20260714T002853_20260714T002910_P05023_F_P_J_001",
        "NISAR_L2_PR_GUNW_026_084_A_030_028_2000_SH_20260726T002852_20260726T002910_20260819T002851_20260819T002909_P05023_N_P_J_001",
    ],
}


def sizes(session, names):
    """Размеры гранул (HEAD, следуя редиректам)."""
    out = {}
    for n in names:
        url = "%s/%s/%s.h5" % (B, n, n)
        r = session.head(url, headers=HDR, allow_redirects=True, timeout=60)
        r.raise_for_status()
        out[n] = int(r.headers["Content-Length"])
        print("[size] %s: %d байт" % (n[:60], out[n]), flush=True)
    return out


def download_parts(session, name, size, deadline):
    """Докачивает parts одной гранули параллельными потоками."""
    dest = OUT / (name + ".h5")
    if dest.exists() and dest.stat().st_size == size:
        return True
    chunk = (size + NCHUNK - 1) // NCHUNK
    ranges = []
    for i in range(NCHUNK):
        s = i * chunk
        e = min((i + 1) * chunk - 1, size - 1)
        if s > e:
            continue
        ranges.append((i, s, e))
    url = "%s/%s/%s.h5" % (B, name, name)
    from concurrent.futures import ThreadPoolExecutor
    import threading

    stop = threading.Event()

    def work(i_s_e):
        i, s, e = i_s_e
        part = OUT / ("%s.h5.part%d" % (name, i))
        while not stop.is_set():
            have = part.stat().st_size if part.exists() else 0
            need = e - s + 1
            if have >= need:
                return True
            try:
                r = session.get(url, headers=dict(
                    HDR, Range="bytes=%d-%d" % (s + have, e)),
                    stream=True, timeout=(20, 90))
                if r.status_code not in (200, 206):
                    time.sleep(3)
                    continue
                with open(part, "ab") as f:
                    t0 = time.time()
                    for blk in r.iter_content(1 << 20):
                        f.write(blk)
                        if time.time() > deadline or stop.is_set():
                            stop.set()
                            return False
                        if time.time() - t0 > 90:  # живой поток
                            t0 = time.time()
            except Exception:
                time.sleep(3)
        return False

    with ThreadPoolExecutor(max_workers=NCHUNK) as ex:
        list(ex.map(work, ranges))
    done = all((OUT / ("%s.h5.part%d" % (name, i))).stat().st_size
               >= e - s + 1 for i, s, e in ranges)
    return done


def assemble(name, size):
    dest = OUT / (name + ".h5")
    if dest.exists() and dest.stat().st_size == size:
        return True
    chunk = (size + NCHUNK - 1) // NCHUNK
    parts = []
    for i in range(NCHUNK):
        s = i * chunk
        e = min((i + 1) * chunk - 1, size - 1)
        if s > e:
            continue
        part = OUT / ("%s.h5.part%d" % (name, i))
        if part.stat().st_size != e - s + 1:
            print("[gap ] %s part%d неполный" % (name[:50], i), flush=True)
            return False
        parts.append(part)
    with open(dest, "wb") as out:
        for p in parts:
            with open(p, "rb") as f:
                while True:
                    blk = f.read(1 << 24)
                    if not blk:
                        break
                    out.write(blk)
    ok = dest.stat().st_size == size
    if ok:
        for p in parts:
            p.unlink()
    return ok


def main(site):
    OUT.mkdir(parents=True, exist_ok=True)
    names = PAIRS[site]
    t_start = time.time()
    deadline = t_start + BUDGET
    sess = requests.Session()
    sess.mount("https://", requests.adapters.HTTPAdapter(
        pool_connections=16, pool_maxsize=16, max_retries=2))
    sz = sizes(sess, names)
    alldone = True
    for n in names:
        d = download_parts(sess, n, sz[n], deadline)
        alldone &= d
        print("[part] %s: %s" % (n[:60], "готов" if d else "недокачан"),
              flush=True)
        if time.time() > deadline:
            break
    if time.time() > deadline:
        print("BUDGET исчерпан — перезапусти для продолжения", flush=True)
        return 2
    for n in names:
        ok = assemble(n, sz[n])
        print("[asm ] %s: %s" % (n[:60], "OK" if ok else "FAIL"), flush=True)
        alldone &= ok
    if alldone:
        print("COMPLETE", flush=True)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
