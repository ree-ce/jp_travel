# JP Travel Project Configuration

## Git Workflow
- **Always commit and push directly to `master`**. Never create feature branches.

## Project Overview
- **Path**: `/Users/reece_chen/Documents/Claude/Projects/JP Travel`
- **Purpose**: Comprehensive Japanese travel planning with flights, events, accommodations, and photo spots
- **Focus Regions**: 関東 (Kanto), 関西 (Kansai), 中部北陸 (Chubu-Hokuriku)

## Available Skills

### search-flights
**Path**: `./.claude/skills/search-flights/search.py`

Google Flights internal API wrapper for ticket price searches. Three modes:

1. **Scan Mode (default)**: Daily lowest prices for fixed trip length
   ```bash
   python3 ./search.py <origin> <dest> <depart_start> <depart_end> <trip_days> [budget] [airlines] [--nonstop]
   ```
   Example: `./search.py TPE JP 2026-07-01 2026-07-31 7 14000 CI,BR --nonstop`

2. **Calendar Grid (--grid)**: Outbound × Return date matrix
   ```bash
   python3 ./search.py --grid <origin> <dest> <out_start> <out_end> <ret_start> <ret_end> [airlines] [--nonstop]
   ```

3. **Calendar Graph (--graph)**: Cross-month price trends (multi-month view)
   ```bash
   python3 ./search.py --graph <origin> <dest> <date_start> <date_end> <min_days> <max_days> [airlines] [--nonstop]
   ```

**Supported Destinations**:
- Country codes expand to major airports: JP → [NRT, HND, KIX, NGO, FUK, CTS, OKA]
- Or explicit airport codes: TPE, NRT, HND, KIX, NGO, etc.

**Flight Constraints**:
- Supported airlines: CI, BR, JX, MM, TR, IT, GK, JL, NH (default)
- `--nonstop` flag filters for direct flights only
- Budget parameter sets max round-trip price in TWD (default 15,000)

**Output Format**:
- **Scan mode**: Detailed flight info with GO (Outbound) + Return recommendations + price rating (超值/便宜/一般/偏高/高)
- **Grid/Graph**: Fast matrix/trend view with lowest prices, no detailed flights

**Rate Limiting**: 1.5s delay between daily queries in scan mode to avoid rate limits. Retry automatically on timeout.

## Data Structure

### Activity JSON Schema
All events in `活動資料/` follow this structure:

```json
{
  "id": "XX001",
  "name_ja": "Japanese name",
  "name_zh": "Traditional Chinese name",
  "date": "YYYY-MM-DD",
  "day_of_week": "曜日",
  "confirmed": true/false,
  "confirmed_note": "出典: [source URL or description]",
  "past_event": false,
  "past_event_note": "[Only if past_event: true]",
  "location_ja": "Location in Japanese",
  "location_zh": "Location in Traditional Chinese",
  "region": "関東/関西/中部北陸",
  "priority": "★★★★★ description",
  "notes": "Details, access info, timing tips",
  "access": "How to get there",
  "source": "https://...",
  "highlights": "What makes it special"
}
```

### Confirmed vs Unconfirmed
- `"confirmed": true` — Official source verified (公式サイト or 信頼できるメディア)
- `"confirmed": false` — Pattern-based prediction, crowdsourced info, or unannounced for 2026
- `"past_event": true` — Already occurred in 2026 (for reference only)
- Always include `confirmed_note` explaining the source or reason for unconfirmed status

### Regions
- **関東**: Tokyo, Kanagawa, Saitama, Chiba, Ibaraki, Tochigi, Gunma
- **関西**: Osaka, Kyoto, Hyogo, Nara, Wakayama, Shiga, Mie
- **中部北陸**: Aichi, Gifu, Nagano, Yamanashi, Shizuoka, Toyama, Ishikawa, Fukui

## Activity Categories

Current activity database:

1. **祭典** (`matsuri_festivals_2026.json`) — Traditional and major festivals
2. **航空祭** (`airshows_2026.json`) — Self-Defense Force air shows
3. **花火大会** (`hanabi_fireworks_2026.json`) — Fireworks festivals (23 events)
4. **紅葉名所** (`koyo_spots_2026.json`) — Autumn foliage viewing locations
5. **紅葉（纜車）** (`ropeway_foliage_routes.json`) — Ropeway/cable car foliage routes (10 routes)
6. **花見スポット** (`sakura_spots.json`) — Cherry blossom viewing spots (7 locations)
7. **富士山撮影スポット** (`fuji_photo_spots.json`) — Mt. Fuji photography locations (4 spots)
8. **艦艇公開** (`naval_openday_2026.json`) — Naval vessel open days (JMSDF)
9. **JAXA公開** (`jaxa_openday_2026.json`) — Space agency facility tours
10. **モータースポーツ** (`motorsports_2026.json`) — Racing events (F1, Super GT, etc.)
11. **工場見学** (`factory_tours.json`) — Industrial tours (Toyota, Mitsubishi, etc.)

## Itinerary Planning

### Timing Assumptions
- **Tokyo (NRT)**: 3.5h airport lead time from city center
- **Osaka (KIX)**: 3.25h airport lead time
- **Nagoya (NGO)**: 2.5h airport lead time
- **Target**: 5–6 day trips combining cheap flights + high-value events

### Candidate Itineraries
See `候選行程/itinerary_candidates.md` for:
- Plan A–E options with flight times, costs, and activities
- Comparison table
- Flight verification checklist

## Web Verification Protocol

**Critical**: All dates must be verified via web search before recording in JSON.
- Never rely on memory or historical patterns
- Always include source URLs in `confirmed_note` field
- Flag unverified future dates with `"confirmed": false`
- Use Agent(subagent_type="general-purpose") for multi-source verification

## Language Settings

This project uses:
- **Conversations**: English (en-US) or Traditional Chinese (zh-TW)
- **Code, comments, variables**: English (en-US) only
- **Documentation**: English or Traditional Chinese
- **Event names**: Japanese + Traditional Chinese translations

## References

- **Event verification sources**:
  - JASDF Air Show Schedule: [dc.watch.impress.co.jp](https://dc.watch.impress.co.jp/)
  - Official tourism sites (city/prefecture level)
  - Major event aggregators (Walker Plus, Nikkei, etc.)
- **Flight data**: Google Flights API (internal RPC)
- **Maps**: Google Maps links for location pins

## Symbols & Conventions

- **Priority Rating**: ★★★★★ (5 = must-do, 1 = optional)
- **Confirmation**: ✓ = verified, ✗ = unconfirmed, ? = needs follow-up
- **Regions**: Always use Japanese kanji (関東/関西/中部北陸)
- **Dates**: Always YYYY-MM-DD format
