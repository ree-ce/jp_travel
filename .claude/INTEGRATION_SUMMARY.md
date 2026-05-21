# JP Travel × google_flight Integration Summary

**整合完成日期**: 2026-05-03

## 整合內容

### 1. ✅ `.claude/skills/` 完整複製
```
.claude/skills/search-flights/
├── search.py          (23 KB) — Google Flights API wrapper
└── SKILL.md           (12 KB) — 技能文檔
```

**來源**: `/Users/reece_chen/Documents/Code/side/google_flight/.claude/skills/`

**同步方式**: 複製檔案，保持獨立維護。未來若 google_flight 有更新，需手動同步或建立符號連結。

---

### 2. ✅ 項目級 `CLAUDE.md` 建立
**檔案**: `.claude/CLAUDE.md`

內容涵蓋：
- 專案概述與目標區域
- search-flights 三模式完整指南（掃描 / 日曆網格 / 折線趨勢）
- 活動資料 JSON 架構定義
- 已驗證日期列表
- 飛行時間假設模型
- 語言與程式碼風格規範

---

### 3. ✅ 整合指南 `INTEGRATION_GUIDE.md`
**檔案**: `.claude/INTEGRATION_GUIDE.md`

快速參考：
- 4 個常見用法示例
- 目的地速查表
- 輸出解讀指南
- 與活動日程結合的高價值行程窗口
- 故障排除表

---

### 4. ✅ 記憶索引 `MEMORY.md`
**檔案**: `.claude/MEMORY.md`

整合型記憶指標，指向：
- 項目目標與約束
- 飛行時間假設
- 活動資料架構
- 已驗證 2026 日期清單

---

## 使用方式

### 立即可用

在 JP Travel 項目內，直接調用技能：

```bash
python3 ./.claude/skills/search-flights/search.py TPE KIX 2026-10-01 2026-10-31 5
```

或參考 `./.claude/INTEGRATION_GUIDE.md` 的範例。

### 關鍵檔案位置

| 用途 | 位置 |
|------|------|
| 專案設定 | `./.claude/CLAUDE.md` |
| 快速參考 | `./.claude/INTEGRATION_GUIDE.md` |
| 技能說明 | `./.claude/skills/search-flights/SKILL.md` |
| 技能實現 | `./.claude/skills/search-flights/search.py` |

---

## 與全局設定的關係

### 全局 `~/.claude/CLAUDE.md`
仍然適用於所有專案：
- 工具使用政策（fd, ast-grep, jq 等）
- 語言要求（英文代碼 + 中文對話）
- 代碼風格規範

### 項目級 `./.claude/CLAUDE.md`
JP Travel 專用：
- 活動資料架構
- 日期驗證協議
- search-flights 使用指南
- 行程規劃約束

**優先級**: 專案級 > 全局級（專案級設定覆蓋全局）

---

## 後續同步

### 若 google_flight 有更新
兩種維護策略：

1. **手動同步**（推薦用於控制）
   ```bash
   cp /Users/reece_chen/Documents/Code/side/google_flight/.claude/skills/search-flights/search.py \
      /Users/reece_chen/Documents/Claude/Projects/JP\ Travel/.claude/skills/search-flights/
   ```

2. **符號連結**（推薦用於自動同步）
   ```bash
   rm -rf ./.claude/skills/search-flights/search.py
   ln -s /Users/reece_chen/Documents/Code/side/google_flight/.claude/skills/search-flights/search.py \
         ./.claude/skills/search-flights/search.py
   ```

### 版本控制
- search.py 的修改應優先在 google_flight 進行
- JP Travel 中的 .md 文檔（CLAUDE.md, INTEGRATION_GUIDE.md）獨立維護

---

## 檢查清單

✅ `.claude/skills/search-flights/` 完整複製  
✅ `.claude/CLAUDE.md` 建立與內容完備  
✅ `.claude/INTEGRATION_GUIDE.md` 建立與範例清晰  
✅ `.claude/MEMORY.md` 索引整合  
✅ 目錄結構清理（移除重複）  
✅ 文件權限正確  

---

## 下一步

1. **測試 search-flights**
   ```bash
   cd /Users/reece_chen/Documents/Claude/Projects/JP\ Travel
   python3 ./.claude/skills/search-flights/search.py TPE NGO 2026-08-01 2026-08-31 5
   ```

2. **建立行程候選時驗證飛行價格**
   - 用 --graph 看季度趨勢
   - 用 --grid 看日期矩陣
   - 用掃描模式確認詳細航班

3. **定期監控並更新 `itinerary_candidates.md`**
   - 新發現的低價窗口
   - 活動日期變化（如非官方公佈但可預測的日期）

4. **考慮自動化**（未來）
   - 每週定時執行 --graph 搜尋，監控特定路線的票價走勢
   - 與 Slack/Mail 通知整合，提醒低價出現
