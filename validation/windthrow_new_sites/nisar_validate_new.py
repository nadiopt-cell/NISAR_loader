# -*- coding: utf-8 -*-
"""Валидация NISAR L-band DiD-детектирования ветровалов на НОВЫХ участках
из обновлённой БД Шихова (ветровалы_3316).

Протокол — как в прошлой валидации (upload/nisar_val/README.md):
  пара GUNW (шторм, интервал (t0,t1] содержит события) + базис-согласованная
  контроль-пара; живой код плагина run_windthrow_did; ref_mask —
  растеризованные полигоны Шихова; лес — Hansen GFC@2026.
Метрики: пиксельные P/R/F1/IoU (лес&валид), локальные в буфере 3 км,
объектные P/R/F1 при IoU >= 0.5; сигнал (AUC/excess/TPR@5%) из отчёта плагина.

Запуск: nisar_validate_new.py <site>
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import geopandas as gpd
import pandas as pd
import rasterio
from rasterio.features import rasterize
from affine import Affine
from pyproj import Transformer
from scipy import ndimage

sys.path.insert(0, "/home/z/my-project/nisar_qgis_work")
from nisar_qgis.nisar_core.processing.windthrow import (  # noqa: E402
    run_windthrow_did, parse_gunw_pair_info,
    hansen_forest_mask_year, DEFAULT_FOREST_FRACTION)
from nisar_qgis.nisar_core.processing.forest_mask import (  # noqa: E402
    hansen_tile_suffixes)
from nisar_qgis.nisar_core.readers import ReaderRegistry  # noqa: E402


def build_forest_mask(georef, year, bbox_wgs84,
                       local_dir=None,
                       forest_fraction=DEFAULT_FOREST_FRACTION):
    """Forest@year на сетке GUNW: доля 30-м лесных пикселей в 80-м ячейке.

    Агрегация numpy (полосы исходного растра + pyproj + bincount):
    каждый 30-м пиксель Hansen относится к той 80-м ячейке, в чей центр
    области он попадает — семантика v2/v3 forest-mask (эквивалентность
    доказана в прошлой валидации: маски совпадают на 99.96%), но память
    предсказуема (~500 МБ вместо OOM на reproject float64).
    """
    local_dir = local_dir or GFC_DIR
    import rasterio
    from rasterio.windows import Window
    from pyproj import Transformer
    H, W = georef.height, georef.width
    ulx, uly = georef.transform[0], georef.transform[3]
    xres, yres = abs(georef.transform[1]), abs(georef.transform[5])
    num = np.zeros(H * W, dtype=np.int64)   # лесные 30-м пиксели
    den = np.zeros(H * W, dtype=np.int64)   # все покрытые 30-м пиксели
    tf = Transformer.from_crs("EPSG:4326", georef.crs_authid, always_xy=True)
    used, warns = 0, []
    ROWS = 256  # полоса строк исходного растра
    for suf in hansen_tile_suffixes(bbox_wgs84):
        tc_path = "%s/Hansen_GFC-2024-v1.12_treecover2000_%s.tif" % (local_dir, suf)
        ly_path = "%s/Hansen_GFC-2024-v1.12_lossyear_%s.tif" % (local_dir, suf)
        try:
            tcs, lys = rasterio.open(tc_path), rasterio.open(ly_path)
        except Exception as exc:  # FileNotFoundError / RasterioIOError
            warns.append("нет тайла Hansen %s (%s)" % (suf, exc))
            continue
        try:
            left, bottom, right, top = tcs.bounds
            ix0 = max(bbox_wgs84[0], left)
            iy0 = max(bbox_wgs84[1], bottom)
            ix1 = min(bbox_wgs84[2], right)
            iy1 = min(bbox_wgs84[3], top)
            if ix0 >= ix1 or iy0 >= iy1:
                continue
            res = (right - left) / tcs.width  # ~0.00025 град/px
            col0 = int(np.floor((ix0 - left) / res))
            col1 = int(np.ceil((ix1 - left) / res))
            row0 = int(np.floor((top - iy1) / res))
            row1 = int(np.ceil((top - iy0) / res))
            col0, col1 = max(col0, 0), min(col1, tcs.width)
            row0, row1 = max(row0, 0), min(row1, tcs.height)
            ncols, nrows = col1 - col0, row1 - row0
            cols_c = left + res * (col0 + np.arange(ncols) + 0.5)
            print(f"    Hansen {suf}: {ncols}x{nrows} px @30 м", flush=True)
            for r0 in range(row0, row1, ROWS):
                r1 = min(r0 + ROWS, row1)
                win = Window(col0, r0, ncols, r1 - r0)
                tc = tcs.read(1, window=win)
                ly = lys.read(1, window=win)
                forest = hansen_forest_mask_year(tc, ly, year)
                # центры 30-м пикселей (строки сверху вниз)
                ys = top - res * (r0 + np.arange(r1 - r0) + 0.5)
                gx, gy = np.meshgrid(cols_c, ys)
                X, Y = tf.transform(gx.ravel(), gy.ravel())
                col = np.floor((X - ulx) / xres).astype(np.int64)
                row = np.floor((uly - Y) / yres).astype(np.int64)
                inside = (col >= 0) & (col < W) & (row >= 0) & (row < H)
                idx = row[inside] * W + col[inside]
                den += np.bincount(idx, minlength=H * W)
                num += np.bincount(idx[forest.ravel()[inside]],
                                   minlength=H * W)
            used += 1
        finally:
            tcs.close()
            lys.close()
    if not used:
        return None, warns or ["тайлы Hansen не прочитаны"]
    frac = num.reshape(H, W) / np.maximum(den.reshape(H, W), 1)
    return (frac >= forest_fraction), warns


DB = "/home/z/my-project/upload/shikhov_upd/vetrovaly_3316/ветровалы_3316.shp"
GFC_DIR = "/home/z/my-project/upload/gfc"
GRAN_DIR = Path("/home/z/my-project/upload/nisar_new")
OUT_ROOT = Path("/home/z/my-project/download/nisar_val_new")

SITES = {
    # регрессионный тест скрипта на уцелевших гранулах прошлой валидации
    "karpinsk_retest": dict(
        label="РЕТЕСТ скрипта: Карпинск 22.06.2026 (4251: 12 га), ожидания из прошлой валидации",
        storm="/home/z/my-project/upload/gunw/NISAR_L2_PR_GUNW_023_093_D_058_024_2000_SH_20260620T154356_20260620T154433_20260702T154356_20260702T154432_P05023_N_F_J_001.h5",
        control="/home/z/my-project/upload/gunw/NISAR_L2_PR_GUNW_024_093_D_058_025_2000_SH_20260702T154356_20260702T154432_20260714T154355_20260714T154431_P05023_F_F_J_001.h5",
    ),
    "nnov_sukhona": dict(
        label="Нижегородская шквал 05.07.2026 (4275: 373 га; 4276: 31 га)",
        storm="NISAR_L2_PR_GUNW_024_099_A_030_025_2000_SH_20260703T012709_20260703T012745_20260715T012709_20260715T012744_P05023_N_F_J_001.h5",
        control="NISAR_L2_PR_GUNW_025_099_A_030_026_2000_SH_20260715T012709_20260715T012744_20260727T012708_20260727T012743_P05023_N_F_J_001.h5",
    ),
    "kostroma_108": dict(
        label="Костромская+Нижегородская 05.07.2026 (4267/4271/4268/4282/4283)",
        storm="NISAR_L2_PR_GUNW_024_108_D_059_025_2000_SH_20260703T164247_20260703T164323_20260715T164246_20260715T164322_P05023_N_F_J_001.h5",
        control="NISAR_L2_PR_GUNW_025_108_D_059_026_2000_SH_20260715T164246_20260715T164322_20260727T164245_20260727T164321_P05023_N_F_J_001.h5",
    ),
    "kirov_slav": dict(
        label="Кировская шквалы 27.07.2026 (4344: 234 га; 4342: 136 га; 4343: 58 га)",
        storm="NISAR_L2_PR_GUNW_026_041_A_032_028_2000_SH_20260723T005500_20260723T005536_20260816T005458_20260816T005534_P05023_N_F_J_001.h5",
        control="NISAR_L2_PR_GUNW_028_041_A_032_030_2000_SH_20260816T005458_20260816T005534_20260909T005458_20260909T005534_P05023_N_F_J_001.h5",
    ),
    "chelyabinsk": dict(
        label="Челябинская шквал 21.06.2026 (4265: 157 га)",
        storm="NISAR_L2_PR_GUNW_023_084_A_030_025_2000_SH_20260620T002854_20260620T002912_20260714T002853_20260714T002910_P05023_F_P_J_001.h5",
        control="NISAR_L2_PR_GUNW_026_084_A_030_028_2000_SH_20260726T002852_20260726T002910_20260819T002851_20260819T002909_P05023_N_P_J_001.h5",
    ),
}


def grid_wgs84_bbox(georef):
    """bbox WGS84 сетки GUNW (края+середины, pyproj 3413->4326)."""
    tr = [float(x) for x in georef.transform]
    w, h = georef.width, georef.height
    ulx, uly = tr[0], tr[3]
    lrx = ulx + tr[1] * w
    lry = uly + tr[5] * h
    pts = [(ulx, uly), (ulx, lry), (lrx, uly), (lrx, lry),
           (ulx, (uly + lry) / 2), (lrx, (uly + lry) / 2),
           ((ulx + lrx) / 2, uly), ((ulx + lrx) / 2, lry)]
    tf = Transformer.from_crs(georef.crs_authid, "EPSG:4326", always_xy=True)
    lons, lats = [], []
    for x, y in pts:
        lon, lat = tf.transform(x, y)
        lons.append(lon)
        lats.append(lat)
    return (min(lons), min(lats), max(lons), max(lats))


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    iou = tp / (tp + fp + fn) if tp + fp + fn else 0.0
    return dict(tp=int(tp), fp=int(fp), fn=int(fn),
                precision=round(p, 4), recall=round(r, 4),
                f1=round(f1, 4), iou=round(iou, 4))


def main(site):
    cfg = SITES[site]
    def _path(p):
        return p if p.startswith("/") else str(GRAN_DIR / p)
    storm_path = _path(cfg["storm"])
    control_path = _path(cfg["control"])
    for p in (storm_path, control_path):
        if not Path(p).exists():
            sys.exit("нет гранулы: %s" % p)

    sp = parse_gunw_pair_info(cfg["storm"])
    cp = parse_gunw_pair_info(cfg["control"])
    t0, t1 = sp.ref_start.date(), sp.sec_start.date()
    c0, c1 = cp.ref_start.date(), cp.sec_start.date()
    print(f"[{site}] шторм {t0} -> {t1} (trk {sp.track}{sp.direction} "
          f"fr {sp.frame}), контроль {c0} -> {c1}")

    # --- 1. геореференс сетки 80 м из шторм-гранулы -------------------------
    storm = ReaderRegistry.open(storm_path)
    georef = storm.georef
    print(f"  сетка {georef.width}x{georef.height} {georef.crs_authid} "
          f"@ {abs(georef.transform[1]):.0f} м")
    ReaderRegistry.close(storm)

    bbox84 = grid_wgs84_bbox(georef)
    print(f"  bbox WGS84: {bbox84[0]:.2f},{bbox84[1]:.2f} - "
          f"{bbox84[2]:.2f},{bbox84[3]:.2f}")

    # --- 2. события Шихова в интервале шторм-пары (t0, t1] -----------------
    gdf = gpd.read_file(DB).to_crs(4326)
    gdf["date_ts"] = pd.to_datetime(gdf["date"], errors="coerce",
                                    format="mixed", dayfirst=True)
    gdf["evid"] = gdf["id"].astype(int)
    m = ((gdf["date_ts"].dt.date > t0) & (gdf["date_ts"].dt.date <= t1))
    cand = gdf[m].copy()
    # пересечение с bbox сетки
    from shapely.geometry import box as sbox
    zone = sbox(*bbox84)
    cand = cand[cand.intersects(zone)].copy()
    # события в контроль-интервале (паразитные для контроля) — только предупреждение
    paras = gdf[((gdf["date_ts"].dt.date > c0) & (gdf["date_ts"].dt.date <= c1))
                & (gdf.intersects(zone))]
    print(f"  событий в шторм-интервале и кадре: {len(cand)} "
          f"(id {sorted(cand['evid'].tolist())}); "
          f"в контроль-интервале: {len(paras)}")

    events = {}
    for evid, grp in cand.groupby("evid"):
        rec = grp.iloc[0]
        events[int(evid)] = dict(
            type=str(rec.get("type", "")),
            date=str(rec["date_ts"].date()),
            area_ha=float(grp["area"].sum()),
            region=str(rec.get("region", "")),
            n_poly=len(grp),
            geom=grp.to_crs(georef.crs_authid)
                   .geometry.union_all(),
        )
        print(f"    {evid} {events[evid]['date']} {events[evid]['type']} "
              f"{events[evid]['area_ha']:.1f} га {events[evid]['region']}")

    if not events:
        sys.exit("нет событий в кадре — валидация бессмысленна")

    # --- 3. растеризация ref (union + по-событийно) -------------------------
    aff = Affine(georef.transform[1], 0.0, georef.transform[0],
                 0.0, georef.transform[5], georef.transform[3])
    shape = (georef.height, georef.width)
    ref = rasterize([(g, 1) for g in [e["geom"] for e in events.values()]],
                    out_shape=shape, transform=aff, fill=0,
                    dtype="uint8").astype(bool)
    ref_events = {}
    for evid, e in events.items():
        ref_events[evid] = rasterize(
            [(e["geom"], 1)], out_shape=shape, transform=aff,
            fill=0, dtype="uint8").astype(bool)
    print(f"  ref: {int(ref.sum())} px ({ref.sum() * 0.64:.0f} га)")

    # --- 4. лесная маска Hansen GFC@2026 (memory-safe num/den) -------------
    forest, fwarn = build_forest_mask(georef, 2026, bbox84)
    if forest is None:
        sys.exit("лесная маска не построена: %s" % fwarn)
    print(f"  лес: {int(forest.sum())} px ({forest.sum() * 0.64:.0f} га), "
          f"предупреждения: {fwarn}")

    # --- 5. прогон живого кода плагина ---------------------------------------
    out_dir = OUT_ROOT / site
    event_date = datetime.fromisoformat(
        min(e["date"] for e in events.values()))
    result = run_windthrow_did(
        storm_path, control_path, output_dir=str(out_dir),
        ref_mask=ref, forest_mask=forest, event_date=event_date)
    if not result.success:
        sys.exit("плагин вернул ошибку: %s" % result.error_message)
    rep = result.metadata
    print(f"  порог {rep['threshold']['value']:.4f}, "
          f"детектировано {rep['detection']['pixels']} px "
          f"({rep['detection']['area_ha']:.0f} га), "
          f"{rep['detection']['objects']} объектов; "
          f"AUC {rep['metrics']['auc']:.3f}, excess "
          f"{rep['metrics']['excess']:.3f}, "
          f"TPR@5% {rep['metrics']['tpr_fpr05']:.2f}; "
          f"флаги: {rep['flags']}")

    # --- 6. метрики против маски детектирования ------------------------------
    with rasterio.open(out_dir / "windthrow_mask.tif") as ds:
        det = ds.read(1) == 1
    with rasterio.open(out_dir / "dcoh.tif") as ds:
        dcoh = ds.read(1)
    valid = np.isfinite(dcoh)

    eval_f = valid & forest
    tp = int((det & ref & eval_f).sum())
    fp = int((det & ~ref & eval_f).sum())
    fn = int((~det & ref & eval_f).sum())
    pixel_metrics = prf(tp, fp, fn)

    # локальные: буфер 3 км вокруг ref, зона = валид (как в прошлой валидации)
    dist = distance_grid(ref, abs(georef.transform[1]))
    zone3k = dist <= 3000.0
    tp_l = int((det & ref & valid).sum())
    fp_l = int((det & ~ref & zone3k & valid).sum())
    fn_l = int((~det & ref & valid).sum())
    pixel_local = prf(tp_l, fp_l, fn_l)

    # объектные: 8-связные блобы vs события, IoU >= 0.5
    labels, n_det = ndimage.label(det, structure=np.ones((3, 3), int))
    sizes = np.bincount(labels.ravel())  # sizes[b] = размер блоба b
    per_event, matched_events, matched_blobs = {}, 0, set()
    for evid, ev in ref_events.items():
        ev_px = int(ev.sum())
        if ev_px == 0:
            per_event[evid] = dict(px=0, best_iou=0.0, matched=False,
                                   overlap_share=0.0, det_px_overlapping=0)
            continue
        lab_in = labels[ev]
        inter = np.bincount(lab_in[lab_in > 0], minlength=n_det + 1)
        best, best_blob = 0.0, -1
        for b in range(1, n_det + 1):
            i = int(inter[b])
            if i == 0:
                continue
            union = int(sizes[b]) + ev_px - i
            iou = i / union
            if iou > best:
                best, best_blob = iou, b
        det_px = int((det & ev).sum())
        if best >= 0.5:
            matched_events += 1
            matched_blobs.add(best_blob)
        per_event[evid] = dict(
            px=ev_px, best_iou=round(float(best), 4),
            matched=bool(best >= 0.5),
            overlap_share=round(det_px / ev_px, 4),
            det_px_overlapping=det_px)
    n_ref_ev = len(ref_events)
    obj_p = len(matched_blobs) / n_det if n_det else 0.0
    obj_r = matched_events / n_ref_ev if n_ref_ev else 0.0
    obj_f1 = 2 * obj_p * obj_r / (obj_p + obj_r) if obj_p + obj_r else 0.0
    object_metrics = dict(
        n_det_objects=int(n_det), n_ref_events=n_ref_ev,
        events_matched=matched_events,
        det_objects_matched=len(matched_blobs),
        precision=round(obj_p, 4), recall=round(obj_r, 4),
        f1=round(obj_f1, 4), per_event=per_event)

    # --- 7. сводка ------------------------------------------------------------
    val = dict(
        site=site, label=cfg["label"],
        storm=cfg["storm"], control=cfg["control"],
        storm_interval=[str(t0), str(t1)],
        control_interval=[str(c0), str(c1)],
        track=f"{sp.track}{sp.direction}", frame=sp.frame,
        event_date=min(e["date"] for e in events.values()),
        event_ids=sorted(events),
        events={str(k): {kk: vv for kk, vv in v.items() if kk != "geom"}
                for k, v in events.items()},
        parasitic_events_in_control=sorted(paras["evid"].astype(int).tolist()),
        forest_mask_used=True, forest_warnings=fwarn,
        plugin_report=rep,
        pixel_metrics=pixel_metrics,
        pixel_metrics_local_3km=pixel_local,
        object_metrics=object_metrics,
        iou_object_threshold=0.5,
    )
    (out_dir / "validation.json").write_text(
        json.dumps(val, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"  пиксельные: P {pixel_metrics['precision']:.3f} "
          f"R {pixel_metrics['recall']:.3f} F1 {pixel_metrics['f1']:.3f} "
          f"IoU {pixel_metrics['iou']:.3f}")
    print(f"  локальные 3 км: P {pixel_local['precision']:.3f} "
          f"R {pixel_local['recall']:.3f} F1 {pixel_local['f1']:.3f}")
    print(f"  объектные IoU>=0.5: P {object_metrics['precision']:.3f} "
          f"R {object_metrics['recall']:.3f} "
          f"(событий совпало {matched_events}/{n_ref_ev})")
    print(f"  -> {out_dir / 'validation.json'}")


def distance_grid(ref, spacing_m):
    from scipy.ndimage import distance_transform_edt
    return distance_transform_edt(~ref) * spacing_m


if __name__ == "__main__":
    main(sys.argv[1])
