# ORIS scripting reference / 腳本指令參考

Scripts are plain Python. Every menu command is available as `run("name", parameter=value)`; the **Recorder** tab writes these lines for you while you work.
腳本就是 Python。所有選單指令都能用 `run("名稱", 參數=值)` 呼叫；操作時「記錄器」分頁會自動幫您寫好。

## Helper functions / 輔助函式

| Function | Purpose | 用途 |
|---|---|---|
| `run(name, **params)` | Run an operation on the current image | 對目前影像執行操作 |
| `roi(kind, points)` / `roi()` | Set / clear the selection. kind: `rect`, `ellipse`, `polygon`, `freehand`, `line`, `point` | 設定／清除選取範圍 |
| `open_image(path)` | Open a file and make it current | 開啟檔案並設為目前影像 |
| `save_image(path)` | Save the current image (`.tif` keeps everything) | 儲存目前影像（`.tif` 保留完整資料） |
| `select_image(name_or_index)` | Switch the current image | 切換目前影像 |
| `image()` | The current image object (`.data` is a NumPy array shaped frames × channels × height × width) | 目前影像物件（`.data` 為 NumPy 陣列） |
| `table(key)` | A results table: `results`, `particles`, `summary`, `cells`, `gel`, `coloc`, `fluor`, `wound`. Has `.rows`, `.cols`, `.to_csv(path)` | 結果表格 |
| `log(text)` | Print to the script output | 輸出訊息 |
| `np` | NumPy | NumPy |

## Example / 範例

```python
# count nuclei in every image of a folder (use Analyze ▸ Batch Process Folder)
run("subtract_background", radius=50.0)
run("count_cells", sigma=1.5, split=True, min_size=20.0, exclude_edges=True)
log(image().name, table("summary").rows[-1]["Count"])
```

## Operations / 操作一覽

| Name | English | 中文 | Parameters (default) |
|---|---|---|---|
| `smooth` | Smooth | 平滑 | — |
| `sharpen` | Sharpen | 銳利化 | — |
| `find_edges` | Find Edges | 尋找邊緣 | — |
| `gaussian` | Gaussian Blur | 高斯模糊 | `sigma`=2.0 |
| `median` | Median | 中值濾鏡 | `radius`=2 |
| `mean` | Mean | 平均濾鏡 | `radius`=2 |
| `minimum` | Minimum | 最小值濾鏡 | `radius`=1 |
| `maximum` | Maximum | 最大值濾鏡 | `radius`=1 |
| `variance` | Variance | 變異數濾鏡 | `radius`=2 |
| `unsharp` | Unsharp Mask | 非銳化遮罩 | `sigma`=1.0, `amount`=0.6 |
| `bandpass` | Bandpass Filter | 帶通濾波 | `large`=40.0, `small`=3.0 |
| `subtract_background` | Subtract Background | 扣除背景 | `radius`=50.0, `light_background`=False |
| `enhance_contrast` | Enhance Contrast | 增強對比 | `saturated`=0.35 |
| `equalize` | Equalize Histogram | 直方圖等化 | — |
| `clahe` | Local Contrast (CLAHE) | 局部對比增強（CLAHE） | `clip_limit`=0.01 |
| `invert` | Invert | 反相 | — |
| `add` | Add | 加 | `value`=25.0 |
| `subtract` | Subtract | 減 | `value`=25.0 |
| `multiply` | Multiply | 乘 | `value`=1.25 |
| `divide` | Divide | 除 | `value`=1.25 |
| `gamma` | Gamma | Gamma | `value`=0.5 |
| `log` | Log | 對數 | — |
| `sqrt` | Square Root | 平方根 | — |
| `distance_map` | Distance Map | 距離圖 | — |
| `erode` | Erode | 侵蝕 | `iterations`=1 |
| `dilate` | Dilate | 膨脹 | `iterations`=1 |
| `open` | Open | 斷開（開運算） | `iterations`=1 |
| `close` | Close | 閉合（閉運算） | `iterations`=1 |
| `fill_holes` | Fill Holes | 填補孔洞 | — |
| `outline` | Outline | 輪廓 | — |
| `skeletonize` | Skeletonize | 骨架化 | — |
| `watershed` | Watershed | 分水嶺分割 | `tolerance`=1.0 |
| `to_8bit` | 8-bit | 8 位元 | — |
| `to_16bit` | 16-bit | 16 位元 | — |
| `to_32bit` | 32-bit | 32 位元 | — |
| `to_rgb` | RGB Color | RGB 彩色 | — |
| `crop` | Crop | 裁切 | — |
| `duplicate` | Duplicate | 複製影像 | `whole_stack`=True |
| `flip_horizontal` | Flip Horizontally | 水平翻轉 | — |
| `flip_vertical` | Flip Vertically | 垂直翻轉 | — |
| `rotate_right` | Rotate 90° Right | 向右旋轉 90° | — |
| `rotate_left` | Rotate 90° Left | 向左旋轉 90° | — |
| `rotate` | Rotate | 旋轉 | `angle`=15.0, `enlarge`=False, `interpolation`='bilinear' (nearest / bilinear / bicubic) |
| `scale` | Scale | 調整大小 | `factor`=0.5, `interpolation`='bilinear' (nearest / bilinear / bicubic) |
| `clear` | Clear Inside Selection | 清除選取範圍內 | — |
| `clear_outside` | Clear Outside Selection | 清除選取範圍外 | — |
| `z_project` | Z Project | Z 投影 | `method`='max' (max / min / mean / sum / sd / median) |
| `split_channels` | Split Channels | 分離通道 | — |
| `merge_channels` | Merge Channels | 合併通道 | `c1`='', `c2`='', `c3`='none', `c4`='none' |
| `images_to_stack` | Images to Stack | 影像合併為堆疊 | — |
| `stack_to_images` | Stack to Images | 堆疊拆成影像 | — |
| `image_calculator` | Image Calculator | 影像計算機 | `image1`='', `operation`='subtract' (add / subtract / multiply / divide / difference / average / min / max / and / or / xor), `image2`='', `float_result`=False |
| `set_scale` | Set Scale | 設定比例尺 | `distance`=1.0, `known`=1.0, `unit`='µm' |
| `set_lut` | Set Lookup Table | 設定色彩對應表 | `name`='grays' (grays / inverted / red / green / blue / cyan / magenta / yellow / fire / viridis) |
| `set_range` | Set Display Range | 設定顯示範圍 | `lower`=0.0, `upper`=255.0 |
| `auto_contrast` | Auto Contrast | 自動對比 | `saturated`=0.35 |
| `reset_contrast` | Reset Contrast | 重設對比 | — |
| `apply_contrast` | Apply Contrast | 套用對比 | — |
| `set_threshold` | Set Threshold | 設定閾值 | `method`='otsu' (otsu / li / triangle / yen / isodata / mean / minimum / manual), `background`='auto' (auto / dark / light), `lower`=0.0, `upper`=0.0 |
| `clear_threshold` | Clear Threshold | 清除閾值 | — |
| `make_binary` | Make Binary | 轉為二值影像 | — |
| `scale_bar` | Scale Bar | 加上比例尺 | `length`=100.0, `thickness`=4, `color`='white' (white / black / yellow), `position`='lower_right' (lower_right / lower_left / upper_right / upper_left), `label`=True |
| `rename` | Rename | 重新命名 | `name`='' |
| `clear_overlay` | Remove Overlay | 移除疊加標註 | — |
| `select` | Select | 選取 | `kind`='rect', `points`=() |
| `composite` | Composite Mode | 合成顯示模式 | `on`=True |
| `measure` | Measure | 測量 | — |
| `measure_all` | Measure All ROIs | 測量所有 ROI | — |
| `analyze_particles` | Analyze Particles | 顆粒分析 | `min_size`=0.0, `max_size`=0.0, `min_circ`=0.0, `max_circ`=1.0, `exclude_edges`=False, `include_holes`=False, `show_outlines`=True, `add_to_manager`=False, `all_frames`=False |
| `count_cells` | Count Cells | 細胞計數 | `sigma`=1.5, `bg_radius`=0.0, `method`='otsu' (otsu / li / triangle / yen / isodata / mean / minimum), `background`='auto' (auto / dark / light), `split`=True, `tolerance`=1.0, `min_size`=0.0, `max_size`=0.0, `min_circ`=0.0, `exclude_edges`=False, `add_to_manager`=False, `all_frames`=False |
| `wound_healing` | Wound Healing | 傷口癒合 | `radius`=8, `sensitivity`=1.0, `min_area`=1.0, `keep_largest`=False, `all_frames`=True |
| `colocalization` | Colocalization | 共定位分析 | `ch1`=0, `ch2`=1, `threshold`='costes' (costes / otsu / manual / none), `t1`=0.0, `t2`=0.0 |
| `fluorescence` | Fluorescence Intensity | 螢光強度 | `background`='auto' (auto / roi / value), `value`=0.0, `all_channels`=True |
| `gel` | Western Blot | Western Blot | `strips`=(), `axis`='row' (row / lane), `lanes`=0, `mode`='auto' (auto / even), `polarity`='auto' (auto / dark / light), `bg_radius`=0, `prominence`=5.0, `control`='', `reference`=1 |

Sizes (`min_size`, `max_size`) are areas in calibrated units²; `max_size=0` means no upper limit. 
尺寸（`min_size`、`max_size`）為校正後單位的面積；`max_size=0` 表示不設上限。
